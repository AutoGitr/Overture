"""Artwork service operations."""

lazy import logging
lazy from collections.abc import Sequence
lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import (
    ArtFileFacts,
    clear_art_selection,
    read_art_slot,
    record_art_file,
    select_art,
)
lazy from ...db.completion import holds_files
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import ITEM_ART_TYPES, ArtType, ImageSize, JobType, MediaType
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.art import (
    ArtMatchResponse,
    ArtSourcesResponse,
    SaveArtRequest,
)
lazy from ...schemas.collections import CollectionArtwork, collection_artwork
lazy from ...schemas.common import SaveSelectionResponse, Status, StatusResponse
lazy from ...schemas.library import ItemSelectionResponse
lazy from ...utils.art_urls import public_art_url
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import (
    RateLimitedError,
    fetch_image,
    inspect_saved_image,
    is_valid_aspect_ratio,
    is_valid_image_format,
    raise_if_rate_limited,
    sniff_image_size,
)
lazy from ...utils.security import remove_sensitive_url_params
lazy from ...utils.ssrf import is_private_url
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections import COLLECTIONS_LOCK
lazy from ..downloads.queue import AssetScope, JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..library.items import emit_library_item_upserted, require_item
lazy from ..public_dataset.schema.contract import canonical_art_url
lazy from ..storage.assets import AssetStorage
lazy from ..storage.image_cache import ImageCache
lazy from .candidates import ArtCandidates, CandidatePolicy, CandidateSources
lazy from .matcher import ArtMatcher

logger = logging.getLogger(__name__)


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


async def _validate_art_url(target_url: str, *, trusted_media_server: bool) -> None:
    """Reject a URL Overture will not download from.

    Raises:
        PublicServiceError: When the format is unsupported, or the URL points
            somewhere only the server can reach.
    """
    if not is_valid_image_format(target_url):
        raise PublicServiceError(400, "Only JPG and PNG formats are allowed.")
    if not trusted_media_server and await is_private_url(target_url):
        raise PublicServiceError(
            400,
            "Private/Local URLs are not allowed in the database.",
        )


async def _require_valid_aspect_ratio(
    db: AsyncSession, art_type: ArtType, width: int, height: int
) -> None:
    """Check the image's shape against the configured tolerance.

    Raises:
        PublicServiceError: When the aspect ratio is outside the tolerance.
    """
    settings_row = await get_app_settings(db)
    if not is_valid_aspect_ratio(
        width, height, art_type, settings_row.aspect_ratio_tolerance
    ):
        raise PublicServiceError(
            400,
            f"Invalid aspect ratio for {art_type.replace('_', ' ')}.",
        )


@dataclass(frozen=True, slots=True)
class ArtSelection:
    """A validated artwork choice, ready to record for any slot.

    ``stored_url`` is ``None`` for a media-server image, which has no storable
    link: its download records the slot when it lands.
    """

    target_url: str
    stored_url: str | None


class ArtService:
    """Consolidated artwork domain service."""

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
        self._config = app_config
        self._database = database
        self._asset_storage = asset_storage
        self._matcher = matcher
        self._downloads = downloads
        self._publisher = publisher
        self._provider_registry = provider_registry
        self._candidates = candidates
        self._image_clients = image_clients
        self._image_cache = image_cache

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

    async def _resolve_art_dimensions(
        self,
        target_url: str,
        *,
        width: int | None,
        height: int | None,
        trusted_media_server: bool,
    ) -> tuple[int, int]:
        """Return the image's dimensions, fetching them when the client omitted them.

        Raises:
            PublicServiceError: When the remote image cannot be measured.
        """
        if width is not None and height is not None:
            return width, height

        try:
            raise_if_rate_limited(target_url)
            width, height = await sniff_image_size(
                target_url,
                await self._image_clients.get_client(target_url),
                allow_private=trusted_media_server,
                headers=self._provider_registry.provider.get_download_headers(
                    target_url
                ),
            )
        except RateLimitedError as exc:
            raise PublicServiceError(503, str(exc)) from exc
        if not width or not height:
            raise PublicServiceError(
                400,
                "Could not validate remote image dimensions or content type.",
            )
        return width, height

    async def prepare_selection(
        self, art_type: ArtType, body: SaveArtRequest
    ) -> ArtSelection:
        """Validate the chosen artwork before anything is recorded."""
        try:
            target_url = canonical_art_url(remove_sensitive_url_params(body.url))
        except ValueError as exc:
            raise PublicServiceError(400, f"{exc}.") from exc
        trusted_media_server = self._config.is_trusted_media_server_url(target_url)

        await _validate_art_url(target_url, trusted_media_server=trusted_media_server)
        width, height = await self._resolve_art_dimensions(
            target_url,
            width=body.width,
            height=body.height,
            trusted_media_server=trusted_media_server,
        )
        async with self._database.read_session() as db:
            await _require_valid_aspect_ratio(db, art_type, width, height)
        return ArtSelection(
            target_url=target_url,
            stored_url=await public_art_url(target_url, app_config=self._config),
        )

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
        and Retry saved downloads can restore it. An item without a local
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
        selection = await self.prepare_selection(art_type, body)
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

    async def _require_collection(
        self,
        db: AsyncSession,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
    ) -> MediaCollection:
        if art_type.owned_by_season:
            raise PublicServiceError(
                422, "Collections have posters and backgrounds only"
            )
        row = await CollectionRepository(db).get_listed(collection_id, media_type)
        if (
            row is None
            or row.server_type is not self._provider_registry.provider.server_type
        ):
            raise PublicServiceError(404, "Collection not found")
        return row

    async def get_collection_sources(
        self, collection_id: int, media_type: MediaType, art_type: ArtType
    ) -> ArtSourcesResponse:
        """Offer collection art through the shared candidate and slot pipeline."""
        async with self._database.read_session() as db:
            row = await self._require_collection(
                db, collection_id, media_type, art_type
            )
            policy = CandidatePolicy.of(await get_app_settings(db))
        sources = await self._candidates.gather_collection(row, art_type, policy)
        return ArtSourcesResponse(
            sources=sources.by_source, current_url=read_art_slot(row, art_type).url
        )

    async def save_collection(
        self,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        body: SaveArtRequest,
    ) -> StatusResponse:
        """Upload validated bytes and record their art slot."""
        async with self._database.read_session() as db:
            await self._require_collection(db, collection_id, media_type, art_type)
        selection = await self.prepare_selection(art_type, body)
        trusted = self._config.is_trusted_media_server_url(selection.target_url)
        fetched = await fetch_image(
            selection.target_url,
            await self._image_clients.get_client(selection.target_url),
            allow_private=trusted,
            headers=self._provider_registry.provider.get_download_headers(
                selection.target_url
            ),
        )
        _, width, height = await owned_thread(inspect_saved_image, fetched.data)
        async with self._database.read_session() as db:
            await _require_valid_aspect_ratio(db, art_type, width, height)
        phash = await self._matcher.phash.compute_from_bytes(fetched.data)
        original = await self._image_cache.store_original(fetched.data)
        stat = await owned_thread(original.path.stat)
        async with (
            self._asset_storage.asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_storage.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as db:
                row = await self._require_collection(
                    db, collection_id, media_type, art_type
                )
            if row.server_item_id is None:
                raise PublicServiceError(
                    409, "The collection is inactive and has no server copy"
                )
            await self._provider_registry.provider.upload_collection_art(
                row.server_item_id, art_type, fetched.data, fetched.media_type
            )
            async with self._database.write_session() as db:
                row = await self._require_collection(
                    db, collection_id, media_type, art_type
                )
                if selection.stored_url:
                    select_art(row, art_type, selection.stored_url)
                record_art_file(
                    row,
                    art_type,
                    ArtFileFacts(
                        original.file_hash,
                        phash,
                        width,
                        height,
                        stat.st_mtime_ns,
                        stat.st_size,
                    ),
                )
                row.updated_at = utc_now()
                # A stable provider path still needs a new browser cache version.
                if art_type is ArtType.POSTER:
                    row.thumb_url = original.file_hash
                else:
                    row.art_url = original.file_hash
                db.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return StatusResponse(status=Status.OK)

    async def clear_collection(
        self, collection_id: int, media_type: MediaType, art_type: ArtType | None
    ) -> CollectionArtwork:
        """Forget collection artwork selections while preserving server images."""
        async with (
            self._asset_storage.asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_storage.asset_locks.acquire(f"collection:{collection_id}"),
            self._database.write_session() as db,
        ):
            row = await self._require_collection(
                db, collection_id, media_type, art_type or ArtType.POSTER
            )
            for slot_type in (art_type,) if art_type is not None else ITEM_ART_TYPES:
                clear_art_selection(row, slot_type)
            row.updated_at = utc_now()
            db.add(row)
            result = collection_artwork(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return result

    async def match_collection(
        self,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        threshold: int,
    ) -> ArtMatchResponse:
        """Compare collection candidates using the shared pHash ranking and cache."""
        async with self._database.read_session() as db:
            row = await self._require_collection(
                db, collection_id, media_type, art_type
            )
        if row.tmdb_collection_id is None:
            raise PublicServiceError(
                422, "Set a TMDB collection ID before matching artwork"
            )
        if row.server_item_id is None:
            raise PublicServiceError(
                409, "The collection is inactive and has no server copy"
            )
        if (current_url := row.server_image_url(art_type)) is None:
            raise PublicServiceError(422, "The collection has no image to match")
        request = await self._provider_registry.provider.build_collection_image_request(
            row.server_item_id, art_type, ImageSize.DISPLAY, current_url=current_url
        )
        fetched = await fetch_image(
            request.url,
            await self._image_clients.get_client(request.url),
            allow_private=True,
            headers=request.headers,
            params=request.params,
        )
        reference = await self._matcher.phash.compute_from_bytes(fetched.data)
        sources = await self.get_collection_sources(collection_id, media_type, art_type)
        candidates = list(
            {
                candidate.url: candidate
                for group in sources.sources.values()
                for candidate in group
            }.values()
        )
        comparison = await self._matcher.match_candidates(
            reference, candidates, threshold
        )
        return ArtMatchResponse(
            matches=comparison.matches,
            total_compared=comparison.compared,
            prefiltered=comparison.prefiltered,
            failed=comparison.failed,
            errors=comparison.errors,
            reference="media_server",
        )
