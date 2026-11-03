"""Artwork service operations."""

lazy from collections.abc import Sequence

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import (
    clear_art_selection,
    read_art_slot,
    select_art,
)
lazy from ...db.completion import holds_files
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import (
    ITEM_ART_TYPES,
    ArtType,
    AssetScope,
    JobType,
)
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.art import (
    ArtMatchResponse,
    ArtSourcesResponse,
    SaveArtRequest,
)
lazy from ...schemas.common import SaveSelectionResponse, Status, StatusResponse
lazy from ...schemas.library import ItemSelectionResponse
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import (
    RateLimitedError,
    raise_if_rate_limited,
)
lazy from ...utils.time import utc_now
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..library.items import emit_library_item_upserted, require_item
lazy from ..storage.assets import AssetStorage
lazy from ..storage.image_cache import ImageCache
lazy from .candidates import ArtCandidates, CandidatePolicy, CandidateSources
lazy from .choice import ArtSelection, ArtSelector
lazy from .collection_art import CollectionArtService
lazy from .matcher import ArtMatcher


async def _require_art_target(
    db: AsyncSession,
    item: MediaItem,
    art_type: ArtType,
    season_id: int | None,
) -> MediaItem | Season:
    """Return the owner of the requested slot, refusing to guess at it.

    Raises:
        PublicServiceError: When a season-owned slot names no reachable season.
    """
    target = await SeasonRepository(db).art_owner(item, art_type, season_id)
    if target is None:
        raise PublicServiceError(
            400, f"{art_type.value} needs a season_id naming a season of this item"
        )
    return target


class ArtService:
    """Artwork of library items and their seasons.

    Collection artwork is :attr:`collections`; both validate choices through
    :attr:`selector`.
    """

    def __init__(
        self,
        *,
        app_config: Settings,
        database: Database,
        asset_storage: AssetStorage,
        matcher: ArtMatcher,
        downloads: DownloadService,
        publisher: protocols.EventPublisher,
        provider_registry: ProviderRegistry,
        candidates: ArtCandidates,
        image_clients: ProxyClientManager,
        image_cache: ImageCache,
    ) -> None:
        self._database = database
        self._asset_storage = asset_storage
        self._matcher = matcher
        self._downloads = downloads
        self._publisher = publisher
        self._candidates = candidates
        self.selector = ArtSelector(
            app_config=app_config,
            database=database,
            provider_registry=provider_registry,
            image_clients=image_clients,
        )
        self.collections = CollectionArtService(
            app_config=app_config,
            database=database,
            asset_locks=asset_storage.asset_locks,
            matcher=matcher,
            publisher=publisher,
            provider_registry=provider_registry,
            candidates=candidates,
            image_clients=image_clients,
            image_cache=image_cache,
            selector=self.selector,
        )

    async def _gather(
        self,
        item: MediaItem,
        art_type: ArtType,
        *,
        season_id: int | None,
        season_num: int | None,
    ) -> CandidateSources:
        """Return every source's options for one slot under the saved settings."""
        async with self._database.read_session() as db:
            policy = CandidatePolicy.of(await get_app_settings(db))
        return await self._candidates.gather(
            item,
            art_type,
            season_id=season_id,
            season_num=season_num,
            policy=policy,
            include_overturedb=True,
        )

    async def get_sources(
        self,
        item_id: int,
        art_type: ArtType,
        season_id: int | None = None,
    ) -> ArtSourcesResponse:
        """Fetch artwork options from TMDB, OvertureDB and the media server."""
        async with self._database.read_session() as db:
            item = await require_item(db, item_id)
            target = await SeasonRepository(db).art_owner(item, art_type, season_id)
        sources = await self._gather(
            item,
            art_type,
            season_id=season_id,
            season_num=target.season_num if isinstance(target, Season) else None,
        )
        return ArtSourcesResponse(
            sources=sources.by_source,
            current_url=read_art_slot(target, art_type).url if target else None,
        )

    async def sources_for(
        self, item: MediaItem, art_type: ArtType, season_num: int | None
    ) -> ArtSourcesResponse:
        """Fetch artwork options for an unsaved item, which no server holds."""
        sources = await self._gather(
            item, art_type, season_id=None, season_num=season_num
        )
        return ArtSourcesResponse(sources=sources.by_source)

    async def record_selection(
        self,
        db: AsyncSession,
        item: MediaItem,
        target: MediaItem | Season,
        art_type: ArtType,
        selection: ArtSelection,
    ) -> tuple[str | None, bool]:
        """Record the choice; return its download job and whether it is new.

        The choice is saved before any download, so it survives a failed one
        and the next Assets run can restore it. An item without a local
        folder downloads nothing: the choice is all it records.

        Raises:
            PublicServiceError: When an item without a folder is given a
                media-server image, which only a download could record.
        """
        if not holds_files(item):
            if selection.stored_url is None:
                raise PublicServiceError(
                    400, "Media server artwork needs an item with a local folder."
                )
            select_art(target, art_type, selection.stored_url)
            db.add(target)
            await auto_unmonitor_completed(db, item)
            return None, False

        if selection.stored_url:
            select_art(target, art_type, selection.stored_url)
            db.add(target)
        if item.id is None:
            raise RuntimeError("A stored item needs its ID to queue downloads")
        return await self._downloads.queue_job(
            db,
            JobTarget.art(
                item.id,
                art_type,
                selection.target_url,
                season_id=target.id if target is not item else None,
            ),
        )

    async def save(
        self,
        item_id: int,
        art_type: ArtType,
        body: SaveArtRequest,
        season_id: int | None = None,
    ) -> ItemSelectionResponse:
        """Validate the chosen artwork, record it, and enqueue its download."""
        selection = await self.selector.prepare(art_type, body)
        async with (
            self._asset_storage.asset_locks.acquire(item_id),
            self._database.write_session() as db,
        ):
            item = await require_item(db, item_id)
            target = await _require_art_target(db, item, art_type, season_id)
            job_id, created = await self.record_selection(
                db, item, target, art_type, selection
            )

        await self._downloads.committed(db)
        read = await emit_library_item_upserted(
            item_id, "art.save", self._publisher, database=self._database
        )
        if read is None:
            raise PublicServiceError(404, "Item not found")
        return ItemSelectionResponse(
            selection=SaveSelectionResponse.of(job_id, created=created), item=read
        )

    async def clear(
        self,
        item_id: int,
        art_type: ArtType,
        season_id: int | None = None,
    ) -> StatusResponse:
        """Forget one slot's selected URL; the local file and its facts stay.

        A season poster without *season_id* forgets every season's at once.
        """
        async with (
            self._asset_storage.asset_locks.acquire(item_id),
            self._database.write_session() as db,
        ):
            item = await require_item(db, item_id)
            targets: Sequence[MediaItem | Season] = (
                await SeasonRepository(db).list_for_item(item_id)
                if art_type == ArtType.SEASON_POSTER and season_id is None
                else [await _require_art_target(db, item, art_type, season_id)]
            )
            for target in targets:
                clear_art_selection(target, art_type)
                db.add(target)
            await self._downloads.cancel_assets(
                db,
                AssetScope(
                    item_id,
                    job_type=JobType.ART,
                    art_type=art_type,
                    season_id=season_id,
                ),
            )

        await self._downloads.committed(db)
        await emit_library_item_upserted(
            item_id, "art.clear", self._publisher, database=self._database
        )
        return StatusResponse(status=Status.CLEARED)

    async def clear_all(self, item_id: int) -> StatusResponse:
        """Forget every artwork selection of an item and its seasons.

        Local files are not touched, so their recorded facts stay as they are.
        """
        async with (
            self._asset_storage.asset_locks.acquire(item_id),
            self._database.write_session() as db,
        ):
            item = await require_item(db, item_id)
            for art_type in ITEM_ART_TYPES:
                clear_art_selection(item, art_type)
            db.add(item)

            for season in await SeasonRepository(db).list_for_item(item_id):
                clear_art_selection(season, ArtType.SEASON_POSTER)
                db.add(season)
            await self._downloads.cancel_assets(
                db, AssetScope(item_id, job_type=JobType.ART)
            )

        await self._downloads.committed(db)
        await emit_library_item_upserted(
            item_id, "art.clear_all", self._publisher, database=self._database
        )
        return StatusResponse(status=Status.CLEARED)

    async def match(
        self,
        item_id: int,
        art_type: ArtType,
        threshold: int,
        season_id: int | None = None,
    ) -> ArtMatchResponse:
        """Run pHash matching for one slot and update match timestamps."""
        try:
            # Candidates come from several image hosts; while one is paused,
            # matching would wait it out or compare without its images.
            raise_if_rate_limited()
        except RateLimitedError as exc:
            raise PublicServiceError(503, str(exc)) from exc
        async with self._database.read_session() as db:
            item = await require_item(db, item_id)
            await _require_art_target(db, item, art_type, season_id)

        outcome = await self._matcher.match_item_art(
            item_id=item_id,
            art_type=art_type,
            threshold=threshold,
            season_id=season_id,
            include_overturedb=True,
        )

        now = utc_now()
        async with self._database.write_session() as db:
            item = await require_item(db, item_id)
            target = await _require_art_target(db, item, art_type, season_id)
            item.last_matched_at = now
            db.add(item)
            if target is not item:
                target.last_matched_at = now
                db.add(target)

        await emit_library_item_upserted(
            item_id, "art.match", self._publisher, database=self._database
        )

        return outcome.response
