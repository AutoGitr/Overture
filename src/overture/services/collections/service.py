"""Collection service operations."""

lazy import logging
lazy from pathlib import Path

lazy from fastapi import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.public_dataset import PublicDatasetCollection
lazy from ...db.session import Database
lazy from ...db.theme_file import record_theme_file
lazy from ...domain import ArtType, CollectionMatch, ImageSize, MediaType
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.adapters import UploadThemes
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.collections import (
    CollectionDetail,
    CollectionMatchRequest,
    CollectionMember,
    CollectionRead,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
    collection_read,
    collection_theme_status_response,
)
lazy from ...schemas.common import (
    BulkMonitorResponse,
    EnqueuedJobResponse,
    MonitoredResponse,
    Status,
)
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..downloads.collection_theme import (
    collection_theme_unavailable,
    collection_themes_unavailable,
    theme_folder,
)
lazy from ..downloads.queue import AssetScope, JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..provider_images import proxy_provider_image
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from ..themes.youtube_resolver import DownloadError
lazy from .matching import apply_match

logger = logging.getLogger(__name__)


async def catalog_collections(
    session: AsyncSession, tmdb_ids: set[int], *, app_config: Settings
) -> dict[int, PublicDatasetCollection]:
    """Return the catalog's entries for these TMDB collections, if it is enabled."""
    schedule = await load_schedule(
        session, PUBLIC_DATASET_SCHEDULE, timezone=app_config.TZ
    )
    if not schedule.enabled or not tmdb_ids:
        return {}
    return await PublicDatasetRepository(session).collections_by_tmdb_id(tmdb_ids)


class CollectionsService:
    """Consolidated collections domain service."""

    def __init__(
        self,
        *,
        database: Database,
        provider_registry: ProviderRegistry,
        publisher: protocols.EventPublisher,
        downloads: DownloadService,
        proxy_clients: ProxyClientManager,
        app_config: Settings,
    ) -> None:
        self._database = database
        self._provider_registry = provider_registry
        self._publisher = publisher
        self._downloads = downloads
        self._proxy_clients = proxy_clients
        self._app_config = app_config

    def _provider(self) -> CollectionProvider:
        """Return the media server's provider when it supports collections.

        Raises:
            PublicServiceError: When the media server has no collections.
        """
        provider = self._provider_registry.collections
        if provider is None:
            raise PublicServiceError(
                400, "Collections are only supported for Plex and Jellyfin."
            )
        return provider

    async def _require(
        self, session: AsyncSession, collection_id: int, media_type: MediaType
    ) -> MediaCollection:
        """Return a listed collection of the requested media type.

        Raises:
            PublicServiceError: When the last sync listed no such collection.
        """
        provider = self._provider()
        row = await CollectionRepository(session).get_listed(collection_id, media_type)
        if row is None or row.server_type is not provider.server_type:
            raise PublicServiceError(
                404, "Collection not found for the selected media type"
            )
        return row

    async def list_collections(self, media_type: MediaType) -> list[CollectionRead]:
        """Return the collections the last sync listed for the media type."""
        self._provider()
        async with self._database.read_session() as session:
            rows = await CollectionRepository(session).list_listed(media_type)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id for row in rows if row.tmdb_collection_id},
                app_config=self._app_config,
            )
        return [
            collection_read(row, catalog.get(row.tmdb_collection_id or 0))
            for row in rows
        ]

    async def get_collection(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionDetail:
        """Return one collection with its members and catalog entry."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            members = await CollectionRepository(session).members(row.id or 0)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
                app_config=self._app_config,
            )
        entry = catalog.get(row.tmdb_collection_id or 0)
        reason = await collection_theme_unavailable(
            row, provider=self._provider(), app_config=self._app_config
        )
        return CollectionDetail(
            **collection_read(row, entry).model_dump(),
            members=sorted(
                (
                    CollectionMember(
                        id=member.id or 0,
                        title=member.title,
                        year=member.year,
                        media_type=member.media_type,
                        tmdb_id=member.tmdb_id,
                    )
                    for member in members
                ),
                key=lambda member: (member.year or 0, member.title.casefold()),
            ),
            theme_unavailable=reason,
            theme_writable=reason is None,
            catalog_entry_key=f"tmdb-{entry.tmdb_id}" if entry else None,
            catalog_title=entry.title if entry else None,
            youtube_id_overturedb=entry.youtube_id_overturedb if entry else None,
            youtube_id_themerrdb=entry.youtube_id_themerrdb if entry else None,
        )

    async def get_collection_theme(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionThemeStatusResponse:
        """Return the current theme status for a collection."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
        return collection_theme_status_response(collection_read(row, None))

    async def set_collection_theme(
        self, collection_id: int, body: SetCollectionThemeRequest
    ) -> EnqueuedJobResponse:
        """Queue a YouTube track to become the theme of a collection."""
        reason = collection_themes_unavailable(self._provider(), self._app_config)
        if reason is not None:
            raise PublicServiceError(400, reason)
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, body.media_type)
        target = JobTarget.collection_theme(collection_id, row.title, body.youtube_id)
        async with self._downloads.asset_locks.acquire(target.slot.lock_key):
            reason = await collection_theme_unavailable(
                row, provider=self._provider(), app_config=self._app_config
            )
            if reason:
                raise PublicServiceError(400, reason)
            async with self._database.write_session() as session:
                await self._require(session, collection_id, body.media_type)
                job_id, _ = await self._downloads.queue_job(session, target)
        await self._downloads.committed(session)
        return EnqueuedJobResponse(job_id=job_id)

    async def _remove_server_theme(self, collection_id: int) -> None:
        """Delete the theme the server holds for a collection."""
        provider = self._provider()
        async with self._database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None:
            raise PublicServiceError(404, "Collection not found")
        if isinstance(provider.collections, UploadThemes):
            await provider.delete_collection_theme(row.server_item_id)
            return
        try:
            folder = await theme_folder(
                collection_id, app_config=self._app_config, database=self._database
            )
        except DownloadError as exc:
            raise PublicServiceError(400, str(exc)) from exc
        await owned_thread(Path.unlink, folder / THEME_FILENAME, missing_ok=True)
        await provider.refresh_item(row.server_item_id, unlock=())

    async def delete_collection_theme(
        self, collection_id: int, media_type: MediaType
    ) -> DeleteCollectionThemeResponse:
        """Remove the theme from a collection and clear its stored record."""
        async with self._database.read_session() as session:
            await self._require(session, collection_id, media_type)
        scope = AssetScope(collection_id=collection_id)
        async with self._downloads.asset_locks.acquire(scope.lock_key):
            await self._remove_server_theme(collection_id)
            async with self._database.write_session() as db:
                row = await CollectionRepository(db).get(collection_id, media_type)
                if row is not None:
                    row.sqlmodel_update(
                        {
                            "youtube_id": None,
                            "youtube_id_source": None,
                            "youtube_title": None,
                            "youtube_duration": None,
                            "server_theme_id": None,
                            "updated_at": utc_now(),
                        }
                    )
                    record_theme_file(row, None)
                    db.add(row)
                await self._downloads.cancel_assets(db, scope)
        await self._downloads.committed(db)

        cleared_status = collection_theme_status(
            server_has_theme=False, youtube_id=None
        )
        await self._publisher.broadcast(
            "collection.theme.updated",
            {
                "collection_id": collection_id,
                "media_type": media_type,
                "has_theme": False,
                "youtube_id": None,
                "youtube_title": None,
                "youtube_duration": None,
                "theme_status": cleared_status,
            },
        )
        return DeleteCollectionThemeResponse(
            status=Status.OK, has_theme=False, theme_status=cleared_status
        )

    async def set_collection_monitored(
        self, collection_id: int, media_type: MediaType, monitored: bool
    ) -> MonitoredResponse:
        """Set whether a collection is monitored."""
        async with self._database.write_session() as session:
            row = await self._require(session, collection_id, media_type)
            row.monitored = monitored
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return MonitoredResponse(monitored=monitored)

    async def bulk_set_collection_monitored(
        self, collection_ids: list[int], media_type: MediaType, monitored: bool
    ) -> BulkMonitorResponse:
        """Set the monitored flag for multiple collections at once."""
        self._provider()
        async with self._database.write_session() as db:
            updated = await CollectionRepository(db).bulk_set_monitored(
                collection_ids, media_type, monitored, timestamp=utc_now()
            )
        await self._publisher.broadcast("collections.changed")
        return BulkMonitorResponse(updated=updated)

    async def set_match(
        self, collection_id: int, body: CollectionMatchRequest
    ) -> CollectionDetail:
        """Match a collection to a TMDB collection, or keep it unmatched."""
        async with self._database.write_session() as session:
            row = await self._require(session, collection_id, body.media_type)
            row.tmdb_collection_id = body.tmdb_collection_id
            row.tmdb_match = (
                CollectionMatch.MANUAL
                if body.tmdb_collection_id is not None
                else CollectionMatch.UNMATCHED
            )
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, body.media_type)

    async def reset_match(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionDetail:
        """Let the server's ID and the members decide the match again."""
        async with self._database.write_session() as session:
            row = await self._require(session, collection_id, media_type)
            row.tmdb_match = CollectionMatch.AUTO
            member_ids = await CollectionRepository(session).member_ids(row.id or 0)
            facts = await MediaItemRepository(session).tmdb_collection_ids(member_ids)
            facts.extend([None] * max(0, row.child_count - len(facts)))
            row.tmdb_collection_id = None
            apply_match(row, facts if media_type is MediaType.MOVIE else [])
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, media_type)

    async def proxy_collection_image(
        self, collection_id: int, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy a collection's poster or background with bounded response size."""
        provider = self._provider()
        if art_type.owned_by_season:
            raise PublicServiceError(404, "Collection image not found")
        async with self._database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None or row.last_synced_at is None:
            raise PublicServiceError(404, "Collection not found")
        request = await provider.build_collection_image_request(
            row.server_item_id, art_type, size
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
