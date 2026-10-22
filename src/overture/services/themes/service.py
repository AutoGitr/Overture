"""Theme route-facing service operations."""

lazy import logging

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...db.completion import holds_files
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import clear_theme_selection, select_theme
lazy from ...domain import JobType, ThemeIdSource
lazy from ...schemas.common import SaveSelectionResponse, Status, StatusResponse
lazy from ...schemas.library import ItemSelectionResponse
lazy from ...schemas.themes import (
    SearchRequest,
    ThemeSearchResponse,
    ThemeSearchResult,
)
lazy from ...utils.errors import PublicServiceError
lazy from ..downloads.queue import AssetScope, JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..library.items import (
    emit_library_item_upserted,
    library_item_read,
    require_item,
)
lazy from ..storage.assets import AssetStorage
lazy from .youtube_resolver import YouTubeResolver

logger = logging.getLogger(__name__)


class ThemesService:
    """Domain service managing YouTube theme search, download, and clearance."""

    def __init__(
        self,
        *,
        database: Database,
        asset_storage: AssetStorage,
        downloads: DownloadService,
        publisher: protocols.EventPublisher,
        youtube_resolver: YouTubeResolver,
    ) -> None:
        self._database = database
        self._asset_storage = asset_storage
        self._downloads = downloads
        self._publisher = publisher
        self._youtube = youtube_resolver

    async def search(
        self,
        body: SearchRequest,
    ) -> ThemeSearchResponse:
        """Search YouTube for theme music, filtered by duration limits."""
        async with self._database.read_session() as db:
            app_settings = await get_app_settings(db)
        min_duration = app_settings.min_duration_seconds
        max_duration = app_settings.max_duration_seconds

        try:
            results = await self._youtube.search(body.query, body.limit, body.video_ids)
        except (OSError, ValueError) as exc:
            raise PublicServiceError(502, str(exc)) from exc
        explicit_ids = set(body.video_ids)
        filtered = [
            result
            for result in results
            if result.id in explicit_ids
            or min_duration <= (result.duration or 0) <= max_duration
        ]
        return ThemeSearchResponse(results=filtered)

    async def video_metadata(self, youtube_id: str) -> ThemeSearchResult | None:
        """Return the video's title and duration, or ``None`` when unavailable.

        Only a selection without a download needs this, and a missing title
        must not refuse the selection.
        """
        try:
            results = await self._youtube.search("", 1, [youtube_id])
        except (OSError, ValueError) as exc:
            logger.warning("YouTube metadata lookup failed: %s", exc)
            return None
        return next((result for result in results if result.id == youtube_id), None)

    async def record_selection(
        self,
        db: AsyncSession,
        item: MediaItem,
        youtube_id: str,
        metadata: ThemeSearchResult | None,
    ) -> tuple[str | None, bool]:
        """Record the choice; return its download job and whether it is new.

        An item with a local folder records the theme once its download lands.
        One without a folder downloads nothing, so the choice is recorded now
        with *metadata*.
        """
        if not holds_files(item):
            select_theme(
                item,
                youtube_id,
                source=ThemeIdSource.SELECTION,
                title=metadata.title if metadata else None,
                duration=metadata.duration if metadata else None,
            )
            db.add(item)
            await auto_unmonitor_completed(db, item)
            return None, False
        if item.id is None:
            raise RuntimeError("A stored item needs its ID to queue downloads")
        return await self._downloads.queue_job(db, JobTarget.theme(item.id, youtube_id))

    async def select(self, item_id: int, youtube_id: str) -> ItemSelectionResponse:
        """Create or reuse a theme download job, or record a bare selection."""
        async with self._database.read_session() as db:
            files = holds_files(await require_item(db, item_id))
        metadata = None if files else await self.video_metadata(youtube_id)

        async with (
            self._asset_storage.asset_locks.acquire(item_id),
            self._database.write_session() as db,
        ):
            item = await require_item(db, item_id)
            job_id, created = await self.record_selection(
                db, item, youtube_id, metadata
            )

        await self._downloads.committed(db)
        # A queued download records the theme once it finishes; until then the
        # item is unchanged and nothing is announced.
        read = (
            await library_item_read(item_id, database=self._database)
            if job_id is not None
            else await emit_library_item_upserted(
                item_id, "themes.select", self._publisher, database=self._database
            )
        )
        if read is None:
            raise PublicServiceError(404, "Item not found")
        return ItemSelectionResponse(
            selection=SaveSelectionResponse.of(job_id, created=created), item=read
        )

    async def clear(
        self,
        item_id: int,
    ) -> StatusResponse:
        """Clear saved YouTube provenance without changing the local file."""
        async with (
            self._asset_storage.asset_locks.acquire(item_id),
            self._database.write_session() as db,
        ):
            clear_theme_selection(await require_item(db, item_id))
            await self._downloads.cancel_assets(
                db, AssetScope(item_id, job_type=JobType.THEME)
            )

        await self._downloads.committed(db)
        await emit_library_item_upserted(
            item_id, "themes.clear", self._publisher, database=self._database
        )

        return StatusResponse(status=Status.CLEARED)
