"""Library service operations."""

lazy import logging
lazy from pathlib import Path

lazy from fastapi.responses import Response
lazy from sqlmodel import select

lazy from ... import protocols
lazy from ...db.models.art import ArtSlot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import (
    ArtType,
    AssetScope,
    BulkItemOperationKind,
    ImageSize,
    JobType,
    MediaType,
    media_sort_key,
)
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.libraries import LibraryRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.records import RecordRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...repositories.terms import TermRepository
lazy from ...schemas.common import MonitoredResponse
lazy from ...schemas.library import (
    BulkItemOperation,
    BulkItemOperationResult,
    FolderRootsResponse,
    LibrarySectionRead,
    MediaItemListResponse,
    MediaItemRead,
    SeasonRead,
    folder_roots_response,
)
lazy from ...schemas.records import DatabaseRecord
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import UnsupportedImageFormatError
lazy from ...utils.security import sanitise_error
lazy from ...utils.threads import owned_thread
lazy from ..art.service import ArtService
lazy from ..downloads.service import DownloadService
lazy from ..provider_images import proxy_provider_image
lazy from ..removal import AssetRemover
lazy from ..server_identity import resolve_server_item_id
lazy from ..storage.assets import (
    AssetStorage,
    MissingLocalPathError,
    PathTraversalError,
    require_folder_path,
)
lazy from ..storage.image_cache import CachedOriginal, ImageCache
lazy from ..storage.responses import cached_image_response
lazy from ..themes.service import ThemesService
lazy from .items import (
    emit_library_item_removed,
    emit_library_item_upserted,
    media_item_reads_with_catalog_status,
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
        image_cache: ImageCache,
        provider_registry: ProviderRegistry,
        proxy_clients: ProxyClientManager,
        art: ArtService,
        themes: ThemesService,
        remover: AssetRemover,
    ) -> None:
        self._art = art
        self._themes = themes
        self._remover = remover
        self._downloads = downloads
        self._database = database
        self._publisher = publisher
        self._storage = asset_storage
        self._image_cache = image_cache
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
        """Return the libraries of a media type, movies first, then by title."""
        async with self._database.read_session() as db:
            counts = await LibraryRepository(db).counts(media_type)
        return [
            LibrarySectionRead(
                id=library.id,
                title=library.title,
                media_type=library.media_type,
                count=count,
            )
            for library, count in sorted(
                counts,
                key=lambda entry: media_sort_key(
                    entry[0].media_type, entry[0].title, entry[0].id
                ),
            )
        ]

    async def get_folder_roots(self) -> FolderRootsResponse:
        """Return unique root folder paths derived from media item folders."""
        async with self._database.read_session() as db:
            return folder_roots_response(await MediaItemRepository(db).folder_roots())

    async def list_items(
        self, *, media_type: MediaType | None = None
    ) -> MediaItemListResponse:
        """List all visible media items, optionally of one type.

        The client filters, searches and sorts the full list itself.
        """
        async with self._database.read_session() as db:
            items = await MediaItemRepository(db).list_visible(media_type)
            reads = await media_item_reads_with_catalog_status(db, items)
        return MediaItemListResponse(items=reads, total=len(reads))

    async def get_item(self, item_id: int) -> MediaItemRead:
        """Get a single media item."""
        async with self._database.read_session() as db:
            item = await require_item(db, item_id)
            return (await media_item_reads_with_catalog_status(db, [item]))[0]

    async def item_record(self, item_id: int) -> DatabaseRecord:
        """Return an item's stored rows and what the API derives from them."""
        async with self._database.read_session() as db:
            item = await require_item(db, item_id)
            read = (await media_item_reads_with_catalog_status(db, [item]))[0]
            stored = await RecordRepository(db).rows(MediaItem, item_id)
            values = await TermRepository(db).values_of(item_id)
        return DatabaseRecord.of(stored, read, values)

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

        Clearing or deleting cancels the affected downloads. Deleting files or
        the server's copies goes item by item, each committed on its own.
        """
        removal = body.removal
        if body.operation in {"artwork", "themes"} and (
            removal.delete_file or removal.delete_from_server
        ):
            return await self._remove_each(body)
        cancelled = _CANCELLED_JOBS.get(body.operation, ())
        async with self._database.write_session() as db:
            if cancelled:
                await self._downloads.cancel_items(db, body.item_ids, cancelled)
            ids = await MediaItemRepository(db).bulk_operate(
                body.item_ids, body.operation
            )
        await self._downloads.committed(db)
        result = BulkItemOperationResult(item_ids=ids, operation=body.operation)
        if ids:
            await self._publisher.broadcast(
                "library.items.changed", result.model_dump(mode="json")
            )
        return result

    async def _remove_each(self, body: BulkItemOperation) -> BulkItemOperationResult:
        """Remove each item's artwork or theme, counting the ones that fail."""
        if body.operation == "artwork" and body.removal.delete_from_server:
            self._remover.require_art_deletion()
        result = BulkItemOperationResult(item_ids=[], operation=body.operation)
        for item_id in dict.fromkeys(body.item_ids):
            try:
                if body.operation == "artwork":
                    await self._art.remove(item_id, "art", body.removal)
                else:
                    await self._themes.remove(item_id, body.removal)
            except (MediaServerError, OSError, PathTraversalError) as exc:
                result.errors[item_id] = sanitise_error(str(exc))
            except PublicServiceError as exc:
                result.errors[item_id] = exc.message
            else:
                result.item_ids.append(item_id)
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

    async def get_seasons(self, item_id: int) -> list[SeasonRead]:
        """Get a show's tracked seasons."""
        async with self._database.read_session() as db:
            item = await db.get(MediaItem, item_id)
            if item is None:
                return []
            seasons = await SeasonRepository(db).list_tracked_for_item(item_id)
        return season_reads(item, seasons)

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

    async def _restore_original(
        self,
        owner_id: int,
        art_type: ArtType,
        file_hash: str,
    ) -> CachedOriginal:
        """Keep the slot's file again when the cache has lost its image.

        Raises:
            PublicServiceError: When the file is gone, or is no longer the image
                the slot records, which the next refresh of the item records.
        """
        async with self._database.read_session() as db:
            if art_type.owned_by_season:
                season = await db.get(Season, owner_id)
                if not season:
                    raise PublicServiceError(404, "Not found")
                item = await require_item(db, season.media_item_id)
            else:
                season = None
                item = await require_item(db, owner_id)
        folder = await self._item_folder(item)
        path = await owned_thread(
            self._storage.find_local_art_path, art_type, item=item, season=season
        )
        if path is not None:
            try:
                original = await self._image_cache.import_original(path, folder)
            except FileNotFoundError, PathTraversalError:
                original = None
            except UnsupportedImageFormatError as exc:
                raise PublicServiceError(422, "Unreadable image file") from exc
            if original is not None and original.file_hash == file_hash:
                return original
        raise PublicServiceError(404, "File not found")

    async def _serve_cached_image(
        self,
        owner_id: int,
        art_type: ArtType,
        *,
        file_hash: str | None,
        size: ImageSize | None,
        version: str | None,
    ) -> Response:
        """Serve the image a slot records from the cache, or its thumbnail."""
        if file_hash is None:
            raise PublicServiceError(404, "File not found")
        return await cached_image_response(
            self._image_cache,
            file_hash,
            restore=lambda: self._restore_original(owner_id, art_type, file_hash),
            size=size,
            current=version == file_hash,
        )

    async def serve_local_season_image(
        self,
        *,
        season_id: int,
        size: ImageSize | None,
        version: str | None,
    ) -> Response:
        """Serve a show season poster from the cache, or its thumbnail."""
        async with self._database.read_session() as db:
            file_hash = (
                await db.exec(
                    select(ArtSlot.file_hash).where(
                        ArtSlot.season_id == season_id,
                        ArtSlot.art_type == ArtType.SEASON_POSTER,
                    )
                )
            ).first()
        return await self._serve_cached_image(
            season_id,
            ArtType.SEASON_POSTER,
            file_hash=file_hash,
            size=size,
            version=version,
        )

    async def serve_local_image(
        self,
        *,
        item_id: int,
        art_type: ArtType,
        size: ImageSize | None,
        version: str | None,
    ) -> Response:
        """Serve an item's poster or background from the cache, or its thumbnail."""
        if art_type.owned_by_season:
            raise PublicServiceError(400, "An item has no season artwork")
        async with self._database.read_session() as db:
            file_hash = (
                await db.exec(
                    select(ArtSlot.file_hash).where(
                        ArtSlot.media_item_id == item_id,
                        ArtSlot.art_type == art_type,
                    )
                )
            ).first()
        return await self._serve_cached_image(
            item_id,
            art_type,
            file_hash=file_hash,
            size=size,
            version=version,
        )
