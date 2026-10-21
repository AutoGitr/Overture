"""Collection service operations."""

lazy import logging
lazy from typing import Any

lazy from fastapi import Response

lazy from ... import protocols
lazy from ...db.completion import collection_theme_status
lazy from ...db.session import Database
lazy from ...domain import ArtType, ImageSize, MediaType
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.plex import PlexProvider
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.collection_themes import CollectionThemeRepository
lazy from ...schemas.collections import (
    CollectionRead,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
    collection_read_from_provider,
    collection_theme_status_response,
)
lazy from ...schemas.common import (
    BulkMonitorResponse,
    EnqueuedJobResponse,
    MonitoredResponse,
    Status,
)
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..downloads.queue import AssetScope, JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..provider_images import proxy_provider_image

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._database = database
        self._provider_registry = provider_registry
        self._publisher = publisher
        self._downloads = downloads
        self._proxy_clients = proxy_clients

    def _provider(self) -> PlexProvider:
        """Return the media server's provider when it supports collections.

        Raises:
            PublicServiceError: When the media server has no collections.
        """
        provider = self._provider_registry.collections
        if provider is None:
            raise PublicServiceError(400, "Collections are only supported for Plex.")
        return provider

    async def require_collection(
        self, server_id: str, media_type: MediaType
    ) -> dict[str, Any]:
        """Return one collection of the requested media type.

        Raises:
            PublicServiceError: When the server has no such collection.
        """
        for collection in await self._provider().list_collections(media_type):
            if collection.get("id") == server_id:
                return collection
        raise PublicServiceError(
            404, "Collection not found for the selected media type"
        )

    async def list_collections(self, media_type: MediaType) -> list[CollectionRead]:
        """Return all collections for the given media type from the active server."""
        raw = await self._provider().list_collections(media_type)
        provider_theme_ids = {
            str(collection["id"]): (
                str(collection["theme_id"]) if collection.get("theme_id") else None
            )
            for collection in raw
        }
        async with self._database.write_session() as db:
            theme_map = await CollectionThemeRepository(db).reconcile_provider_themes(
                provider_theme_ids, media_type, timestamp=utc_now()
            )

        output: list[CollectionRead] = []
        for collection in raw:
            row = theme_map.get(collection["id"])
            output.append(
                collection_read_from_provider(
                    collection,
                    youtube_id=row.youtube_id if row else None,
                    youtube_title=row.youtube_title if row else None,
                    youtube_duration=row.youtube_duration if row else None,
                    monitored=row.monitored if row else True,
                )
            )
        return output

    async def get_collection_theme(
        self, server_id: str, media_type: MediaType
    ) -> CollectionThemeStatusResponse:
        """Return the current theme status for a collection."""
        for collection in await self.list_collections(media_type):
            if collection.id == server_id:
                return collection_theme_status_response(collection)
        raise PublicServiceError(
            404, "Collection not found for the selected media type"
        )

    async def set_collection_theme(
        self, server_id: str, body: SetCollectionThemeRequest
    ) -> EnqueuedJobResponse:
        """Queue a YouTube track for upload as the theme for a collection."""
        collection = await self.require_collection(server_id, body.media_type)
        target = JobTarget.collection_theme(
            server_id,
            body.media_type,
            str(collection.get("title") or ""),
            body.youtube_id,
        )
        async with (
            self._downloads.asset_locks.acquire(target.slot.lock_key),
            self._database.write_session() as session,
        ):
            job_id, _ = await self._downloads.queue_job(session, target)
        await self._downloads.committed(session)
        return EnqueuedJobResponse(job_id=job_id)

    async def delete_collection_theme(
        self, server_id: str, media_type: MediaType
    ) -> DeleteCollectionThemeResponse:
        """Remove the theme from a collection and clear the local DB record."""
        await self.require_collection(server_id, media_type)
        scope = AssetScope(collection_server_id=server_id)
        async with self._downloads.asset_locks.acquire(scope.lock_key):
            await self._provider().delete_collection_theme(server_id)
            async with self._database.write_session() as db:
                await CollectionThemeRepository(db).clear_theme(
                    server_id, media_type, timestamp=utc_now()
                )
                await self._downloads.cancel_assets(db, scope)
        await self._downloads.committed(db)

        cleared_status = collection_theme_status(
            server_has_theme=False, youtube_id=None
        )
        await self._publisher.broadcast(
            "collection.theme.updated",
            {
                "server_id": server_id,
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
        self, server_id: str, media_type: MediaType, monitored: bool
    ) -> MonitoredResponse:
        """Set whether a collection is monitored."""
        await self.require_collection(server_id, media_type)
        async with self._database.write_session() as db:
            await CollectionThemeRepository(db).set_monitored(
                server_item_id=server_id,
                media_type=media_type,
                server_type=self._provider().server_type,
                monitored=monitored,
                timestamp=utc_now(),
            )
        return MonitoredResponse(monitored=monitored)

    async def bulk_set_collection_monitored(
        self, collection_ids: list[str], media_type: MediaType, monitored: bool
    ) -> BulkMonitorResponse:
        """Set the monitored flag for multiple collections at once."""
        if not collection_ids:
            return BulkMonitorResponse(updated=0)
        await self.require_collection(collection_ids[0], media_type)
        async with self._database.write_session() as db:
            updated = await CollectionThemeRepository(db).bulk_set_monitored(
                collection_ids,
                media_type,
                monitored,
                server_type=self._provider().server_type,
                timestamp=utc_now(),
            )
        return BulkMonitorResponse(updated=updated)

    async def proxy_collection_image(
        self, server_id: str, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy a collection's poster or background with bounded response size."""
        if art_type.owned_by_season:
            raise PublicServiceError(404, "Collection image not found")
        request = await self._provider().build_collection_image_request(
            server_id, art_type, size
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
