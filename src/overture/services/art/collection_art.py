"""Artwork of media-server collections: candidates, uploads and matching."""

lazy from collections.abc import Callable

lazy from fastapi.responses import FileResponse
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import (
    ArtFileFacts,
    art_file_facts,
    art_generation,
    clear_art_selection,
    read_art_slot,
    record_art_file,
    select_art,
    select_upload,
)
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import (
    ITEM_ART_TYPES,
    UNMANAGED_REFUSAL,
    ArtGeneration,
    ArtSource,
    ArtStyle,
    ArtType,
    CollectionKind,
    CollectionPosterStyle,
    ImageSize,
)
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import (
    ArtCandidate,
    ArtMatchResponse,
    ArtSourcesResponse,
    SaveCollectionArtRequest,
)
lazy from ...schemas.common import Status, StatusResponse
lazy from ...schemas.removal import AssetRemoval
lazy from ...utils.art_urls import public_art_url
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.generated_art import render_art
lazy from ...utils.image import (
    RATE_LIMIT_RETRIES,
    RateLimitedError,
    fetch_image,
    inspect_saved_image,
    raise_if_rate_limited,
)
lazy from ...utils.locks import KeyedLock
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections import COLLECTIONS_LOCK
lazy from ..collections.copies import lead_part
lazy from ..removal import NO_COLLECTION_ART_FILE, AssetRemover
lazy from ..storage.image_cache import CachedOriginal, ImageCache
lazy from ..storage.responses import cached_image_response
lazy from .candidates import ArtCandidates, CandidatePolicy, in_source_order
lazy from .choice import ArtSelector, require_valid_aspect_ratio
lazy from .matcher import ArtMatcher
lazy from .uploads import ArtUploads


def chosen_poster_style(
    art_type: ArtType, candidate: ArtCandidate
) -> CollectionPosterStyle | None:
    """The poster style an automatic choice of *candidate* is saved with.

    A link OvertureDB holds keeps its style there; any other poster is an
    individual one.
    """
    if art_type is not ArtType.POSTER:
        return None
    return candidate.poster_style or CollectionPosterStyle.INDIVIDUAL


def uploaded_image(row: MediaCollection, art_type: ArtType) -> ArtFileFacts | None:
    """Return the facts of the image Overture last uploaded, if it can be compared."""
    facts = art_file_facts(read_art_slot(row, art_type))
    return facts if facts is not None and facts.phash is not None else None


def _headed(row: MediaCollection) -> bool:
    """Whether a poster can show the collection's group above its title.

    A separator's title is its group, so it has no heading.
    """
    return row.kind is not CollectionKind.SEPARATOR and bool(row.group_name)


def _render(
    row: MediaCollection, art_type: ArtType, generation: ArtGeneration
) -> bytes:
    """Render a collection's art as :class:`ArtGeneration` describes it."""
    if art_type is ArtType.BACKGROUND:
        return render_art(art_type, generation.style)
    heading = row.group_name if _headed(row) and not generation.title_only else None
    return render_art(art_type, generation.style, row.title, heading)


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
        uploads: ArtUploads,
        remover: AssetRemover,
    ) -> None:
        self._remover = remover
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
        self._uploads = uploads

    async def _require(
        self,
        db: AsyncSession,
        collection_id: int,
        art_type: ArtType,
        *,
        managed: bool = False,
    ) -> MediaCollection:
        """Return a listed collection; with *managed*, one Overture may change."""
        if art_type.owned_by_season:
            raise PublicServiceError(
                422, "Collections have posters and backgrounds only"
            )
        row = await CollectionRepository(db).get_listed(collection_id)
        if row is None:
            raise PublicServiceError(404, "Collection not found")
        if managed and await CollectionRepository(db).rule(collection_id) is None:
            raise PublicServiceError(409, UNMANAGED_REFUSAL)
        return row

    async def found(self, collection_id: int, art_type: ArtType) -> ArtSourcesResponse:
        """Offer the collection art its sources have, best first."""
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
            policy = CandidatePolicy.of(await get_app_settings(db))
        return await self._found(row, art_type, policy)

    async def _found(
        self, row: MediaCollection, art_type: ArtType, policy: CandidatePolicy
    ) -> ArtSourcesResponse:
        sources = await self._candidates.gather_collection(row, art_type, policy)
        return ArtSourcesResponse(
            sources=sources.by_source, current_url=read_art_slot(row, art_type).url
        )

    async def sources(
        self, collection_id: int, art_type: ArtType
    ) -> ArtSourcesResponse:
        """Offer what sources have, and art generated in each style.

        Posters are generated with the title, under the group when there is one
        and alone; backgrounds without text.
        """
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
            policy = CandidatePolicy.of(await get_app_settings(db))
        found = await self._found(row, art_type, policy)
        variants = (
            (False, True)
            if art_type is ArtType.POSTER and _headed(row)
            else (art_type is ArtType.POSTER,)
        )
        generated = [
            ArtCandidate(
                url=f"/api/collections/{collection_id}/art/{art_type}/generated/{style}"
                + ("?title_only=true" if title_only else ""),
                source=ArtSource.GENERATED,
                art_type=art_type,
                generated=style,
                title_only=title_only,
            )
            for title_only in variants
            for style in ArtStyle
        ]
        return found.model_copy(
            update={
                "sources": in_source_order(
                    {**found.sources, ArtSource.GENERATED: generated}
                )
            }
        )

    async def preview(
        self, collection_id: int, art_type: ArtType, generation: ArtGeneration
    ) -> bytes:
        """Return the PNG choosing *generation* would generate for the collection."""
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
        return await owned_thread(_render, row, art_type, generation)

    async def save(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveCollectionArtRequest,
    ) -> StatusResponse:
        """Apply a choice someone is waiting on; refuse it while its host is paused.

        Raises:
            PublicServiceError: 503 while the link's host is paused.
        """
        if body.url is not None:
            try:
                raise_if_rate_limited(body.url)
            except RateLimitedError as exc:
                raise PublicServiceError(503, str(exc)) from exc
        return await self._apply(collection_id, art_type, body, rate_limit_retries=0)

    async def apply(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveCollectionArtRequest,
    ) -> StatusResponse:
        """Apply a choice a background run made, waiting out a host's rate limits."""
        return await self._apply(
            collection_id, art_type, body, rate_limit_retries=RATE_LIMIT_RETRIES
        )

    async def _apply(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveCollectionArtRequest,
        *,
        rate_limit_retries: int,
    ) -> StatusResponse:
        """Upload validated bytes and record their art slot.

        Art to generate is generated from the collection's title and group, kept
        like an upload, and recorded as generated so a new title generates it
        again.

        Raises:
            PublicServiceError: 422 when a poster link has no poster style, or
                a background has one.
        """
        if (body.poster_style is None) is (
            art_type is ArtType.POSTER and body.url is not None
        ):
            raise PublicServiceError(
                422, "A collection's poster link, and only that, has a poster style"
            )
        generation = body.generation
        if (
            generation is not None
            and generation.title_only
            and art_type is not ArtType.POSTER
        ):
            raise PublicServiceError(422, "Only posters are generated with a title")
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type, managed=True)
        if generation is not None:
            upload_hash = await self._generate(row, art_type, generation)
            await self._choose(
                collection_id,
                art_type,
                SaveCollectionArtRequest(upload_hash=upload_hash),
                generated=generation,
            )
        else:
            await self._choose(
                collection_id, art_type, body, rate_limit_retries=rate_limit_retries
            )
        return StatusResponse(status=Status.OK)

    async def _generate(
        self, row: MediaCollection, art_type: ArtType, generation: ArtGeneration
    ) -> str:
        """Generate the collection's art as *generation* says; return its kept hash."""
        stored = await self._uploads.store(
            await owned_thread(_render, row, art_type, generation)
        )
        return stored.upload_hash

    async def _choose(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveCollectionArtRequest,
        *,
        generated: ArtGeneration | None = None,
        rate_limit_retries: int = 0,
    ) -> None:
        """Record a choice; a link is fetched with *rate_limit_retries*."""
        selection = await self._selector.select(art_type, body)
        if isinstance(selection.source, ArtFileFacts):
            facts = selection.source
            data, media_type = await self._uploads.read(facts.file_hash)
        else:
            data, media_type, facts = await self._fetch(
                selection.source, art_type, rate_limit_retries=rate_limit_retries
            )

        def record(row: MediaCollection) -> None:
            if isinstance(selection.source, ArtFileFacts):
                select_upload(row, art_type, facts.file_hash, generated=generated)
            elif selection.stored_url:
                select_art(
                    row,
                    art_type,
                    selection.stored_url,
                    poster_style=body.poster_style,
                )
            else:
                # A media-server image has no link, and a stored one names other art.
                clear_art_selection(row, art_type)
            record_art_file(row, art_type, facts)

        await self._send(collection_id, art_type, data, media_type, record)

    async def regenerate(
        self, collection_id: int, art_type: ArtType, *, resend: bool
    ) -> None:
        """Generate art again if what it shows changed, or *resend* it."""
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type, managed=True)
        generation = art_generation(read_art_slot(row, art_type))
        if generation is None:
            return
        upload_hash = await self._generate(row, art_type, generation)
        if resend or upload_hash != read_art_slot(row, art_type).upload_hash:
            await self._choose(
                collection_id,
                art_type,
                SaveCollectionArtRequest(upload_hash=upload_hash),
                generated=generation,
            )

    async def reupload(self, collection_id: int, art_type: ArtType) -> None:
        """Send every server copy the slot's image again, and record it as shown.

        The image is the upload the slot selects, else the one Overture last
        uploaded, else its link fetched again: a sync forgets what Overture
        uploaded when the server shows another image, but not the selection.

        Raises:
            PublicServiceError: 409 when the slot holds no image to send, or
                the cache does not keep it.
        """
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
        slot = read_art_slot(row, art_type)
        kept = slot.upload_hash or slot.file_hash
        if kept is None:
            if slot.url is None:
                raise PublicServiceError(409, "Overture has uploaded no image to it")
            await self._choose(
                collection_id,
                art_type,
                SaveCollectionArtRequest(url=slot.url, poster_style=slot.poster_style),
            )
            return
        facts = await self._uploads.facts(kept)
        data, media_type = await self._uploads.read(kept)

        def record(saved: MediaCollection) -> None:
            record_art_file(saved, art_type, facts)

        await self._send(collection_id, art_type, data, media_type, record)

    async def _send(
        self,
        collection_id: int,
        art_type: ArtType,
        data: bytes,
        media_type: str,
        record: Callable[[MediaCollection], None],
    ) -> None:
        """Upload an image to every server copy, then *record* it on the row.

        An inactive collection has no server copy, so the image is only
        recorded; the sync that puts the collection back sends it.
        """
        async with (
            self._asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as db:
                row = await self._require(db, collection_id, art_type)
            for part in row.copies:
                if self._provider_registry.configured_server_id(part.server_id):
                    await self._provider_registry.get(
                        part.server_id
                    ).upload_collection_art(
                        part.server_item_id or "", art_type, data, media_type
                    )
            # The lead copy's image stands for the collection, as sync reads it.
            lead = lead_part(row, self._provider_registry.server_ids())
            server_url = (
                await self._provider_registry.get(
                    lead.server_id
                ).get_collection_image_url(lead.server_item_id or "", art_type)
                if lead is not None
                else None
            )
            async with self._database.write_session() as db:
                row = await self._require(db, collection_id, art_type)
                record(row)
                row.updated_at = utc_now()
                if art_type is ArtType.POSTER:
                    row.thumb_url = server_url
                else:
                    row.art_url = server_url
                db.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )

    async def _fetch(
        self, url: str, art_type: ArtType, *, rate_limit_retries: int
    ) -> tuple[bytes, str, ArtFileFacts]:
        """Download a chosen link, keep it in the image cache and describe it.

        Raises:
            PublicServiceError: When its shape is outside the tolerance.
        """
        trusted = self._config.is_trusted_media_server_url(url)
        fetched = await fetch_image(
            url,
            await self._image_clients.get_client(url),
            allow_private=trusted,
            headers=self._provider_registry.download_headers(url),
            rate_limit_retries=rate_limit_retries,
        )
        _, width, height = await owned_thread(inspect_saved_image, fetched.data)
        async with self._database.read_session() as db:
            await require_valid_aspect_ratio(db, art_type, width, height)
        phash = await self._matcher.phash.compute_from_bytes(fetched.data)
        original = await self._image_cache.store_original(fetched.data)
        await self._image_cache.thumb(original)
        stat = await owned_thread(original.path.stat)
        return (
            fetched.data,
            fetched.media_type,
            ArtFileFacts(
                original.file_hash,
                phash,
                width,
                height,
                stat.st_mtime_ns,
                stat.st_size,
            ),
        )

    async def local_image(
        self,
        collection_id: int,
        art_type: ArtType,
        size: ImageSize | None,
        version: str | None,
    ) -> FileResponse:
        """Serve the image Overture last uploaded to a collection, from the cache.

        The cache is its only copy: the server keeps its own encoding, so a
        lost image is not found until the next upload.

        Raises:
            PublicServiceError: 404 when the collection records no such image.
        """
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
        file_hash = read_art_slot(row, art_type).file_hash
        if file_hash is None:
            raise PublicServiceError(404, "Collection image not found")

        async def lost() -> CachedOriginal:
            raise PublicServiceError(404, "Collection image not found")

        return await cached_image_response(
            self._image_cache,
            file_hash,
            restore=lost,
            size=size,
            current=version == file_hash,
        )

    async def adopt(
        self,
        collection_id: int,
        art_type: ArtType,
        url: str,
        poster_style: CollectionPosterStyle | None,
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
            row = await self._require(db, collection_id, art_type)
            select_art(row, art_type, public, poster_style=poster_style)
            db.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return True

    async def remove(
        self, collection_id: int, art_type: ArtType | None, removal: AssetRemoval
    ) -> StatusResponse:
        """Forget a collection's art, or delete the server's image, or both.

        Without *art_type* both slots are removed. Overture keeps no file of
        collection art, so there is none to delete.

        Raises:
            PublicServiceError: 409 when a file is to be deleted, or the server
                cannot delete artwork.
        """
        if removal.delete_file:
            raise PublicServiceError(409, NO_COLLECTION_ART_FILE)
        art_types = (art_type,) if art_type is not None else ITEM_ART_TYPES
        async with (
            self._asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as db:
                row = await self._require(db, collection_id, art_types[0], managed=True)
            if removal.delete_from_server:
                for slot_type in art_types:
                    await self._remover.delete_collection_art(row, slot_type)
            async with self._database.write_session() as db:
                row = await self._require(db, collection_id, art_types[0])
                for slot_type in art_types:
                    if removal.forget:
                        clear_art_selection(row, slot_type)
                    # What Overture uploaded is gone from the server too.
                    if removal.delete_from_server:
                        record_art_file(row, slot_type, None)
                        if slot_type is ArtType.POSTER:
                            row.thumb_url = None
                        else:
                            row.art_url = None
                row.updated_at = utc_now()
                db.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return StatusResponse(status=Status.OK)

    async def match(
        self, collection_id: int, art_type: ArtType, threshold: int
    ) -> ArtMatchResponse:
        """Compare collection candidates with the collection's image.

        The image Overture last uploaded is the reference, as a local file is
        an item's; without one the media server's image is.
        """
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
        if row.tmdb_collection_id is None:
            raise PublicServiceError(
                422, "Set a TMDB collection ID before matching artwork"
            )
        facts = uploaded_image(row, art_type)
        if facts is not None and facts.phash is not None:
            reference, source = facts.phash, "local_file"
        else:
            reference, source = await self._server_phash(row, art_type), "media_server"
        sources = await self.found(collection_id, art_type)
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
        errors = list(comparison.errors)
        if facts is not None:
            errors.extend(
                await self._matcher.annotate_perfect(facts, comparison.matches)
            )
        return ArtMatchResponse(
            matches=sorted(
                comparison.matches, key=lambda match: not match.perfect_match
            ),
            total_compared=comparison.compared,
            prefiltered=comparison.prefiltered,
            failed=comparison.failed,
            errors=errors,
            reference=source,
        )

    async def _server_phash(self, row: MediaCollection, art_type: ArtType) -> str:
        """Return the pHash of the image the media server shows for the slot.

        Raises:
            PublicServiceError: 422 when the server shows none.
        """
        lead = lead_part(row, self._provider_registry.server_ids())
        if lead is None or (current_url := row.server_image_url(art_type)) is None:
            raise PublicServiceError(422, "The collection has no image to match")
        request = await self._provider_registry.get(
            lead.server_id
        ).build_collection_image_request(
            lead.server_item_id or "",
            art_type,
            ImageSize.DISPLAY,
            current_url=current_url,
        )
        fetched = await fetch_image(
            request.url,
            await self._image_clients.get_client(request.url),
            allow_private=True,
            headers=request.headers,
            params=request.params,
        )
        return await self._matcher.phash.compute_from_bytes(fetched.data)
