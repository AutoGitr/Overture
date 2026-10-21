"""Library service operations."""

lazy import logging
lazy from pathlib import Path

lazy from fastapi.responses import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...db.art_slots import find_art_slot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ArtType, ImageSize, JobType, MediaType, text_sort_key
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.common import MonitoredResponse
lazy from ...schemas.library import (
    BulkItemOperation,
    BulkItemOperationKind,
    BulkItemOperationResult,
    FolderRootsResponse,
    LibrarySectionRead,
    MediaItemListResponse,
    MediaItemRead,
    SeasonRead,
    folder_roots_response,
)
lazy from ...utils.assets import ITEM_ASSET_CANDIDATES
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ..downloads.queue import AssetScope
lazy from ..downloads.service import DownloadService
lazy from ..provider_images import proxy_provider_image
lazy from ..server_identity import resolve_server_item_id
lazy from ..storage.assets import (
    AssetStorage,
    MissingLocalPathError,
    require_folder_path,
)
lazy from ..storage.responses import local_image_response
lazy from .items import (
    emit_library_item_removed,
    emit_library_item_upserted,
    media_item_reads_with_public_dataset_status,
    require_item,
    season_reads,
)

logger = logging.getLogger(__name__)

#: The downloads each bulk operation cancels: clearing a selection, like
#: deleting the item, supersedes its outstanding downloads.
_CANCELLED_JOBS: frozendict[BulkItemOperationKind, tuple[JobType, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "artwork": (JobType.ART,),
        "themes": (JobType.THEME,),
        "delete": (JobType.ART, JobType.THEME),
    }
)


class LibraryService:
    """Consolidated library domain service."""

    def __init__(
        self,
        *,
        database: Database,
        downloads: DownloadService,
        publisher: protocols.EventPublisher,
        asset_storage: AssetStorage,
        provider_registry: ProviderRegistry,
        proxy_clients: ProxyClientManager,
    ) -> None:
        self._downloads = downloads
        self._database = database
        self._publisher = publisher
        self._storage = asset_storage
        self._provider_registry = provider_registry
        self._proxy_clients = proxy_clients

    async def proxy_provider_art(
        self, server_id: str, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy provider art for a media-server item, sized by the server."""
        request = await self._provider_registry.provider.build_provider_art_request(
            server_id, art_type, size
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)

    async def proxy_item_provider_art(
        self, item_id: int, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy the current poster or background for an item."""
        if art_type.owned_by_season:
            raise PublicServiceError(400, "An item has no season artwork")
        async with self._database.read_session() as db:
            item = await db.get(MediaItem, item_id)
        if not item or not item.server_item_id:
            raise PublicServiceError(404, "Item or server ID not found")
        return await self.proxy_provider_art(item.server_item_id, art_type, size)

    async def proxy_season_provider_art(
        self, season_id: int, size: ImageSize | None
    ) -> Response:
        """Proxy the current poster from the media server for a season."""
        async with self._database.read_session() as db:
            season = await db.get(Season, season_id)
            if not season:
                raise PublicServiceError(404, "Season or server ID not found")
            item_id = season.media_item_id
        server_id = await resolve_server_item_id(
            item_id,
            ArtType.SEASON_POSTER,
            season_id,
            database=self._database,
            provider_registry=self._provider_registry,
        )
        if not server_id:
            raise PublicServiceError(404, "Season or server ID not found")
        return await self.proxy_provider_art(server_id, ArtType.SEASON_POSTER, size)

    async def get_libraries(
        self, media_type: MediaType | None
    ) -> list[LibrarySectionRead]:
        """Return all distinct libraries for a media type.

        Libraries are named as the media server names them; while it cannot
        be reached, by their IDs.
        """
        async with self._database.read_session() as db:
            counts = await MediaItemRepository(db).library_counts(media_type)

        try:
            titles = {
                section.key: section.title
                for section in await self._provider_registry.provider.get_sections()
            }
        except MediaServerError as exc:
            logger.debug("Could not read the media server's library names: %s", exc)
            titles = {}

        return [
            LibrarySectionRead(
                id=library_id, title=titles.get(library_id, library_id), count=count
            )
            for library_id, count in sorted(
                counts.items(),
                key=lambda entry: text_sort_key(
                    titles.get(entry[0], entry[0]), entry[0]
                ),
            )
        ]

    async def get_folder_roots(self, db: AsyncSession) -> FolderRootsResponse:
        """Return unique root folder paths derived from media item folders."""
        return folder_roots_response(await MediaItemRepository(db).folder_roots())

    async def list_items(
        self, db: AsyncSession, *, media_type: MediaType | None = None
    ) -> MediaItemListResponse:
        """List all visible media items, optionally of one type.

        The client filters, searches and sorts the full list itself.
        """
        items = await MediaItemRepository(db).list_visible(media_type)
        reads = await media_item_reads_with_public_dataset_status(db, items)
        return MediaItemListResponse(items=reads, total=len(reads))

    async def get_item(self, db: AsyncSession, item_id: int) -> MediaItemRead:
        """Get a single media item."""
        item = await require_item(db, item_id)
        return (await media_item_reads_with_public_dataset_status(db, [item]))[0]

    async def set_monitored(self, item_id: int, monitored: bool) -> MonitoredResponse:
        """Set whether an item is monitored."""
        async with self._database.write_session() as db:
            item = await require_item(db, item_id)
            item.monitored = monitored
            db.add(item)

        await emit_library_item_upserted(
            item_id, "library.monitored", self._publisher, database=self._database
        )
        return MonitoredResponse(monitored=monitored)

    async def bulk_operate_items(
        self, body: BulkItemOperation
    ) -> BulkItemOperationResult:
        """Commit the complete target set before publishing one cache update.

        Clearing or deleting cancels the affected downloads.
        """
        cancelled = _CANCELLED_JOBS.get(body.operation, ())
        async with self._database.write_session() as db:
            if cancelled:
                await self._downloads.cancel_items(db, body.item_ids, cancelled)
            ids = await MediaItemRepository(db).bulk_operate(body)
        await self._downloads.committed(db)
        result = BulkItemOperationResult(item_ids=ids, operation=body.operation)
        if ids:
            await self._publisher.broadcast(
                "library.items.changed", result.model_dump(mode="json")
            )
        return result

    async def delete_item(self, item_id: int) -> None:
        """Delete an item completely from the database."""
        async with (
            self._storage.asset_locks.acquire(item_id),
            self._database.write_session() as db,
        ):
            item = await require_item(db, item_id)
            media_type = item.media_type
            await self._downloads.cancel_assets(db, AssetScope(item_id))
            await db.delete(item)

        await self._downloads.committed(db)
        await emit_library_item_removed(
            item_id, media_type, "library.deleted", self._publisher
        )

    async def get_seasons(self, db: AsyncSession, item_id: int) -> list[SeasonRead]:
        """Get a show's tracked seasons."""
        item = await db.get(MediaItem, item_id)
        if item is None:
            return []
        return season_reads(
            item, await SeasonRepository(db).list_tracked_for_item(item_id)
        )

    @staticmethod
    async def _item_folder(item: MediaItem) -> Path:
        """Return the item's resolved local folder.

        Raises:
            PublicServiceError: When the item has no local folder.
        """
        try:
            return await owned_thread(Path(require_folder_path(item)).resolve)
        except MissingLocalPathError as exc:
            raise PublicServiceError(400, str(exc)) from exc

    async def serve_local_season_image(
        self,
        db: AsyncSession,
        *,
        season_id: int,
        size: ImageSize | None,
        version: str | None,
    ) -> Response:
        """Serve a show season poster from disk, downscaled to *size* if given."""
        season = await db.get(Season, season_id)
        if not season:
            raise PublicServiceError(404, "Not found")
        item = await require_item(db, season.media_item_id)
        folder = await self._item_folder(item)

        local_path = await owned_thread(
            self._storage.find_local_art_path,
            ArtType.SEASON_POSTER,
            item=item,
            season=season,
        )
        if local_path is not None and (
            response := await local_image_response(
                local_path,
                folder,
                slot=find_art_slot(season, ArtType.SEASON_POSTER),
                art_type=ArtType.SEASON_POSTER,
                size=size,
                version=version,
            )
        ):
            return response
        raise PublicServiceError(404, "File not found")

    async def serve_local_image(
        self,
        db: AsyncSession,
        *,
        item_id: int,
        art_type: ArtType,
        size: ImageSize | None,
        version: str | None,
    ) -> Response:
        """Serve a local art file for a movie or show, downscaled to *size* if given."""
        if art_type.owned_by_season:
            raise PublicServiceError(400, "An item has no season artwork")
        item = await require_item(db, item_id)
        folder = await self._item_folder(item)
        slot = find_art_slot(item, art_type)
        for filename in ITEM_ASSET_CANDIDATES[art_type]:
            if response := await local_image_response(
                folder / filename,
                folder,
                slot=slot,
                art_type=art_type,
                size=size,
                version=version,
            ):
                return response
        raise PublicServiceError(404, "File not found")
