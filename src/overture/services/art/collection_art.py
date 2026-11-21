"""Artwork of media-server collections: candidates, uploads and matching."""

lazy import logging
lazy from collections.abc import Callable

lazy from fastapi.responses import FileResponse
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.ledger import (
    ContentFacts,
    Destination,
    Evidence,
    clear_selection,
    confirm_delivery,
    content,
    delivery,
    observe,
    read_asset,
    record_content,
    select_art,
    select_upload,
)
lazy from ...db.ledger import generation as ledger_generation
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
lazy from ...repositories.collection_items import CollectionItemRepository
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
lazy from ...utils.image import inspect_saved_image
lazy from ...utils.image_fetch import (
    RATE_LIMIT_RETRIES,
    RateLimitedError,
    fetch_image,
    raise_if_rate_limited,
)
lazy from ...utils.locks import KeyedLock
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections import COLLECTIONS_LOCK
lazy from ..collections.copies import lead_part
lazy from ..collections.destinations import collection_destinations, place_collection
lazy from ..removal import NO_COLLECTION_ART_FILE, AssetRemover
lazy from ..server_copies import ServerCopies
lazy from ..storage.image_cache import CachedOriginal, ImageCache
lazy from ..storage.responses import cached_image_response
lazy from .candidates import (
    MEMBER_BACKGROUNDS,
    MEMBER_BACKGROUNDS_TOTAL,
    ArtCandidates,
    CandidatePolicy,
    in_source_order,
)
lazy from .choice import ArtSelector, require_valid_aspect_ratio
lazy from .matcher import ArtMatcher
lazy from .phash import PhashService
lazy from .uploads import ArtUploads

logger = logging.getLogger(__name__)


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
        phash: PhashService,
        publisher: protocols.EventPublisher,
        provider_registry: ProviderRegistry,
        candidates: ArtCandidates,
        image_clients: ProxyClientManager,
        image_cache: ImageCache,
        selector: ArtSelector,
        uploads: ArtUploads,
        remover: AssetRemover,
        server_copies: ServerCopies,
    ) -> None:
        self._remover = remover
        self._server_copies = server_copies
        self._config = app_config
        self._database = database
        self._asset_locks = asset_locks
        self._matcher = matcher
        self._phash = phash
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
            sources=sources.by_source,
            current_url=read_asset(row, art_type.server_asset).url,
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
            members = (
                await CollectionItemRepository(db).member_tmdb_titles(
                    collection_id, MEMBER_BACKGROUNDS_TOTAL
                )
                if art_type is ArtType.BACKGROUND
                else []
            )
        found = await self._found(row, art_type, policy)
        # Only the picker offers them: matching a run's collections would
        # fingerprint a hundred more images each.
        from_members = (
            {
                MEMBER_BACKGROUNDS: await self._candidates.member_backgrounds(
                    row.title, members, policy
                )
            }
            if members
            else {}
        )
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
                    {
                        **found.sources,
                        **from_members,
                        ArtSource.GENERATED: generated,
                    }
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
        in the image cache, and recorded as generated so a new title, or a
        cache that lost it, generates it again.

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
            generated = await self._generate(row, art_type, generation)
            await self._choose(
                collection_id,
                art_type,
                SaveCollectionArtRequest(upload_hash=generated.file_hash),
                generated=generation,
            )
        else:
            await self._choose(
                collection_id, art_type, body, rate_limit_retries=rate_limit_retries
            )
        return StatusResponse(status=Status.OK)

    async def _generate(
        self, row: MediaCollection, art_type: ArtType, generation: ArtGeneration
    ) -> CachedOriginal:
        """Generate the collection's art as *generation* says, into the cache."""
        original = await self._image_cache.store_original(
            await owned_thread(_render, row, art_type, generation)
        )
        await self._image_cache.thumb(original)
        return original

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
        kind = art_type.server_asset
        if isinstance(selection.source, ContentFacts):
            content = selection.source
            data, media_type = await self._uploads.read(content.content_hash)
        else:
            data, media_type, content = await self._fetch(
                selection.source, art_type, rate_limit_retries=rate_limit_retries
            )

        def record(row: MediaCollection) -> None:
            if isinstance(selection.source, ContentFacts):
                select_upload(row, kind, content.content_hash, generated=generated)
            elif selection.stored_url:
                select_art(
                    row, kind, selection.stored_url, poster_style=body.poster_style
                )
            else:
                # A media-server image has no link, and a stored one names other art.
                clear_selection(row, kind)
            record_content(row, kind, content)

        await self._send(collection_id, art_type, data, media_type, record)

    async def regenerate(
        self, collection_id: int, art_type: ArtType, *, resend: bool
    ) -> None:
        """Generate art again if what it shows changed, or *resend* it."""
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type, managed=True)
        await self._redraw(collection_id, row, art_type, resend=resend)

    async def _redraw(
        self,
        collection_id: int,
        row: MediaCollection,
        art_type: ArtType,
        *,
        resend: bool,
    ) -> bool:
        """Generate the slot's art again, and send it if it changed or *resend*.

        Returns:
            Whether the slot holds generated art.
        """
        asset = read_asset(row, art_type.server_asset)
        generation = ledger_generation(asset)
        if generation is None:
            return False
        generated = await self._generate(row, art_type, generation)
        if resend or generated.file_hash != asset.upload_hash:
            await self._choose(
                collection_id,
                art_type,
                SaveCollectionArtRequest(upload_hash=generated.file_hash),
                generated=generation,
            )
        return True

    async def reupload(self, collection_id: int, art_type: ArtType) -> None:
        """Send every server copy the asset's content again, and record it delivered.

        The content is the art the asset generates, drawn again, else the image
        Overture keeps for the selection, else its link fetched again.

        Raises:
            PublicServiceError: 409 when the asset selects nothing, or Overture
                no longer holds what it selects.
        """
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
        if await self._redraw(collection_id, row, art_type, resend=True):
            return
        asset = read_asset(row, art_type.server_asset)
        kept = asset.upload_hash or asset.content_hash
        if kept is None or await self._image_cache.original(kept) is None:
            if asset.url is None:
                raise PublicServiceError(409, "Overture holds no image to send to it")
            await self._choose(
                collection_id,
                art_type,
                SaveCollectionArtRequest(
                    url=asset.url, poster_style=asset.poster_style
                ),
            )
            return
        content = await self._uploads.facts(kept)
        data, media_type = await self._uploads.read(kept)

        def record(saved: MediaCollection) -> None:
            record_content(saved, art_type.server_asset, content)

        await self._send(collection_id, art_type, data, media_type, record)

    async def _send(
        self,
        collection_id: int,
        art_type: ArtType,
        data: bytes,
        media_type: str,
        record: Callable[[MediaCollection], None],
    ) -> None:
        """Upload an image to every server copy, then *record* it and the copies.

        Each copy is recorded as holding the content, named by the image link
        the server lists for it now. An inactive collection has no server copy,
        so the content is only recorded; the sync that puts the collection back
        sends it.
        """
        kind = art_type.server_asset
        async with (
            self._asset_locks.acquire(COLLECTIONS_LOCK),
            self._asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as db:
                row = await self._require(db, collection_id, art_type)
            delivered: list[tuple[Destination, str | None]] = []
            for destination in collection_destinations(
                row, kind, self._provider_registry
            ):
                provider = self._provider_registry.get(destination.server_id or 0)
                copy_id = destination.server_item_id or ""
                await provider.upload_collection_art(
                    copy_id, art_type, data, media_type
                )
                delivered.append(
                    (
                        destination,
                        await provider.get_collection_image_url(copy_id, art_type),
                    )
                )
            async with self._database.write_session() as db:
                row = await self._require(db, collection_id, art_type)
                record(row)
                now = utc_now()
                place_collection(row, self._provider_registry)
                for destination, server_url in delivered:
                    confirm_delivery(row, kind, destination, ref=server_url, at=now)
                row.updated_at = now
                db.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )

    async def _fetch(
        self, url: str, art_type: ArtType, *, rate_limit_retries: int
    ) -> tuple[bytes, str, ContentFacts]:
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
        phash = await self._phash.compute_from_bytes(fetched.data)
        original = await self._image_cache.store_original(fetched.data)
        await self._image_cache.thumb(original)
        return (
            fetched.data,
            fetched.media_type,
            ContentFacts(original.file_hash, phash, width, height),
        )

    async def local_image(
        self,
        collection_id: int,
        art_type: ArtType,
        size: ImageSize | None,
        version: str | None,
    ) -> FileResponse:
        """Serve the image Overture last uploaded to a collection, as it keeps it.

        The server keeps its own encoding, so a fetched image the cache lost is
        not found until the next upload; generated art is drawn again.

        Raises:
            PublicServiceError: 404 when the collection records no such image.
        """
        async with self._database.read_session() as db:
            row = await self._require(db, collection_id, art_type)
        file_hash = read_asset(row, art_type.server_asset).content_hash
        if file_hash is None:
            raise PublicServiceError(404, "Collection image not found")

        async def restore() -> CachedOriginal:
            if (generated := await self._regenerated(row, art_type)) is None:
                raise PublicServiceError(404, "Collection image not found")
            return generated

        return await cached_image_response(
            self._image_cache,
            file_hash,
            restore=restore,
            size=size,
            current=version == file_hash,
        )

    async def _regenerated(
        self, row: MediaCollection, art_type: ArtType
    ) -> CachedOriginal | None:
        """Draw the asset's generated art again, if that gives its content."""
        asset = read_asset(row, art_type.server_asset)
        if (generation := ledger_generation(asset)) is None:
            return None
        generated = await self._generate(row, art_type, generation)
        return generated if generated.file_hash == asset.content_hash else None

    async def uploaded(
        self, row: MediaCollection, art_type: ArtType
    ) -> ContentFacts | None:
        """Return the content Overture holds for the asset, fingerprinted.

        Content recorded without a fingerprint is fingerprinted from the copy
        Overture keeps, drawing generated art again if the cache lost it, and
        saved.

        Returns:
            The content, or ``None`` when Overture holds none for the asset.

        Raises:
            PublicServiceError: 409 when Overture no longer holds the image.
        """
        kind = art_type.server_asset
        held = content(read_asset(row, kind))
        if held is None or held.fingerprint is not None:
            return held
        if await self._image_cache.original(held.content_hash) is None:
            await self._regenerated(row, art_type)
        kept = await self._uploads.facts(held.content_hash)
        async with (
            self._asset_locks.acquire(f"collection:{row.id}"),
            self._database.write_session() as db,
        ):
            saved = await CollectionRepository(db).get_listed(row.id or 0)
            # Another upload may have replaced the content meanwhile.
            if saved is not None and read_asset(saved, kind).content_hash == (
                kept.content_hash
            ):
                record_content(saved, kind, kept)
                db.add(saved)
        return kept

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
            select_art(row, art_type.server_asset, public, poster_style=poster_style)
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
                now = utc_now()
                for slot_type in art_types:
                    kind = slot_type.server_asset
                    if removal.forget:
                        clear_selection(row, kind)
                    # What Overture uploaded is gone from the server too.
                    if removal.delete_from_server:
                        for destination in collection_destinations(
                            row, kind, self._provider_registry
                        ):
                            observe(
                                row,
                                kind,
                                destination,
                                Evidence.DIFFERENT,
                                ref=None,
                                at=now,
                            )
                row.updated_at = now
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
        facts = await self.uploaded(row, art_type)
        if facts is not None and facts.fingerprint is not None:
            reference, source = facts.fingerprint, "local_file"
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
                await self._matcher.annotate_perfect(
                    facts.content_hash, comparison.matches
                )
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
        """Return the pHash of the image the lead server copy shows for the asset.

        Raises:
            PublicServiceError: 422 when the server shows none.
        """
        lead = lead_part(row, self._provider_registry.server_ids())
        seen = (
            delivery(
                read_asset(row, art_type.server_asset),
                Destination(lead.server_id, lead.server_item_id),
            )
            if lead is not None
            else None
        )
        if lead is None or seen is None or seen.observed_ref is None:
            raise PublicServiceError(422, "The collection has no image to match")
        return await self._server_copies.collection_image(
            self._provider_registry.get(lead.server_id),
            lead.server_item_id or "",
            art_type,
            seen.observed_ref,
        )
