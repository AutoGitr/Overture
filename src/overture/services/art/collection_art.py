"""Artwork of media-server collections: candidates, uploads and matching."""

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
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import (
    ITEM_ART_TYPES,
    UNMANAGED_REFUSAL,
    ArtType,
    ImageSize,
    MediaType,
)
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import ArtMatchResponse, ArtSourcesResponse, SaveArtRequest
lazy from ...schemas.collections import CollectionArtwork, collection_artwork
lazy from ...schemas.common import Status, StatusResponse
lazy from ...utils.art_urls import public_art_url
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import fetch_image, inspect_saved_image
lazy from ...utils.locks import KeyedLock
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections import COLLECTIONS_LOCK
lazy from ..storage.image_cache import ImageCache
lazy from .candidates import ArtCandidates, CandidatePolicy
lazy from .choice import ArtSelector, require_valid_aspect_ratio
lazy from .matcher import ArtMatcher


class CollectionArtService:
    """Offer, upload, adopt, clear and match the artwork of collections."""

    def __init__(
        self,
        *,
        app_config: Settings,
        database: Database,
        asset_locks: KeyedLock[int | str],
        matcher: ArtMatcher,
        publisher: protocols.EventPublisher,
        provider_registry: ProviderRegistry,
        candidates: ArtCandidates,
        image_clients: ProxyClientManager,
        image_cache: ImageCache,
        selector: ArtSelector,
    ) -> None:
        self._config = app_config
        self._database = database
        self._asset_locks = asset_locks
        self._matcher = matcher
        self._publisher = publisher
        self._provider_registry = provider_registry
        self._candidates = candidates
        self._image_clients = image_clients
        self._image_cache = image_cache
        self._selector = selector

    async def _require(
        self,
        db: AsyncSession,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        *,
        managed: bool = False,
    ) -> MediaCollection:
        """Return a listed collection; with *managed*, one Overture may change."""
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
        if managed and await CollectionRepository(db).rule(collection_id) is None:
            raise PublicServiceError(409, UNMANAGED_REFUSAL)
        return row

    async def sources(
        self, collection_id: int, media_type: MediaType, art_type: ArtType
    ) -> ArtSourcesResponse:
        """Offer collection art through the shared candidate and slot pipeline."""
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, media_type, art_type)
            policy = CandidatePolicy.of(await get_app_settings(db))
        sources = await self._candidates.gather_collection(row, art_type, policy)
        return ArtSourcesResponse(
            sources=sources.by_source, current_url=read_art_slot(row, art_type).url
        )

    async def save(
        self,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        body: SaveArtRequest,
    ) -> StatusResponse:
        """Upload validated bytes and record their art slot."""
        async with self._database.read_session() as db:
            await self._require(db, collection_id, media_type, art_type, managed=True)
        selection = await self._selector.prepare(art_type, body)
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
            await require_valid_aspect_ratio(db, art_type, width, height)
        phash = await self._matcher.phash.compute_from_bytes(fetched.data)
        original = await self._image_cache.store_original(fetched.data)
        stat = await owned_thread(original.path.stat)
        async with (
            self._asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as db:
                row = await self._require(db, collection_id, media_type, art_type)
            if row.server_item_id is None:
                raise PublicServiceError(
                    409, "The collection is inactive and has no server copy"
                )
            await self._provider_registry.provider.upload_collection_art(
                row.server_item_id, art_type, fetched.data, fetched.media_type
            )
            async with self._database.write_session() as db:
                row = await self._require(db, collection_id, media_type, art_type)
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

    async def adopt(
        self, collection_id: int, media_type: MediaType, art_type: ArtType, url: str
    ) -> bool:
        """Save *url* as the selection of art the server already shows.

        Returns:
            Whether it was saved; ``False`` when it is not a public link.
        """
        public = await public_art_url(url, app_config=self._config)
        if public is None:
            return False
        async with (
            self._asset_locks.acquire(f"collection:{collection_id}"),
            self._database.write_session() as db,
        ):
            row = await self._require(db, collection_id, media_type, art_type)
            select_art(row, art_type, public)
            db.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return True

    async def clear(
        self, collection_id: int, media_type: MediaType, art_type: ArtType | None
    ) -> CollectionArtwork:
        """Forget collection artwork selections while preserving server images."""
        async with (
            self._asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_locks.acquire(f"collection:{collection_id}"),
            self._database.write_session() as db,
        ):
            row = await self._require(
                db, collection_id, media_type, art_type or ArtType.POSTER, managed=True
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

    async def match(
        self,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        threshold: int,
    ) -> ArtMatchResponse:
        """Compare collection candidates using the shared pHash ranking and cache."""
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, media_type, art_type)
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
        sources = await self.sources(collection_id, media_type, art_type)
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
