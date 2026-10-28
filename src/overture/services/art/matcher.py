"""ArtMatcher - pHash-based visual art matching."""

lazy import asyncio
lazy import logging
lazy from dataclasses import dataclass, field, replace

lazy import httpx2

lazy from ...config import Settings
lazy from ...db.art_slots import ArtFileFacts, art_file_facts, read_art_slot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import MATCH_THRESHOLD_DEFAULT, ArtSource, ArtType
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...schemas.art import ArtCandidate, ArtMatchResponse, MatchReference
lazy from ...utils.errors import public_error_message
lazy from ..local_assets.service import LocalAssets
lazy from ..server_identity import resolve_server_item_id
lazy from .candidates import ArtCandidates, CandidatePolicy
lazy from .matcher_cache import ArtMatcherCache
lazy from .perfect_match import annotate_perfect_matches, remote_matches_file
lazy from .phash import PhashService
lazy from .selection import resolve_art_target

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ArtMatchOutcome:
    """A slot's match response, with the local file it was compared with."""

    response: ArtMatchResponse
    #: The local file's facts when it was the reference.
    local_file: ArtFileFacts | None = None


@dataclass(slots=True, frozen=True)
class CandidateComparison:
    """How a slot's candidates compared with its reference image."""

    #: Candidates within the threshold, nearest first.
    matches: list[ArtCandidate]
    #: Candidates narrower than the reference, rejected without a fetch.
    prefiltered: int
    compared: int
    #: Candidates whose image could not be fetched or hashed.
    failed: int
    #: Why candidate sources could not be asked.
    errors: list[str] = field(default_factory=list[str])


class ArtMatcher:
    """Matches local art against media server candidates using perceptual hashing."""

    def __init__(
        self,
        *,
        phash: PhashService,
        local_assets: LocalAssets,
        provider_registry: ProviderRegistry,
        candidates: ArtCandidates,
        image_clients: ProxyClientManager,
        cache: ArtMatcherCache | None = None,
        app_config: Settings,
        database: Database,
        compare_concurrency: int,
    ) -> None:
        self._app_config = app_config
        #: Candidate images fetched and hashed at once while matching one slot.
        self._compare_concurrency = compare_concurrency
        self._database = database
        self.phash = phash
        self._local_assets = local_assets
        self.provider_registry = provider_registry
        self._candidates = candidates
        self._cache = cache or ArtMatcherCache(
            phash=phash,
            provider_registry=provider_registry,
            image_clients=image_clients,
            app_config=app_config,
        )

    async def close(self) -> None:
        """Stop cache work before its HTTP clients and hash pool."""
        await self._cache.close()

    async def match_candidates(
        self,
        reference_phash: str,
        candidates: list[ArtCandidate],
        threshold: int = MATCH_THRESHOLD_DEFAULT,
        reference_width: int = 0,
    ) -> CandidateComparison:
        """Compare *reference_phash* against candidate images.

        Candidates narrower than the reference cannot be the same artwork at
        its quality, so they are counted as prefiltered without a fetch.
        """
        filtered = [
            candidate
            for candidate in candidates
            if not (
                reference_width
                and (width := candidate.width or 0)
                and width < reference_width
            )
        ]
        compared = 0
        pending = iter(filtered)
        results: list[ArtCandidate] = []

        async def compare(candidate: ArtCandidate) -> None:
            nonlocal compared
            candidate_phash = await self._cache.cached_url_phash(
                candidate.preview_url or candidate.url
            )
            if candidate_phash is None:
                return
            try:
                distance = self.phash.hamming_distance(reference_phash, candidate_phash)
            except ValueError as exc:
                logger.debug("Could not compare a candidate: %s", exc)
                return
            compared += 1
            if distance <= threshold:
                results.append(candidate.model_copy(update={"hamming": distance}))

        async def consume() -> None:
            for candidate in pending:
                await compare(candidate)

        async with asyncio.TaskGroup() as group:
            for _ in range(min(self._compare_concurrency, len(filtered))):
                group.create_task(consume())

        results.sort(
            key=lambda match: (
                match.hamming,
                -match.area,
                0 if match.source == ArtSource.TMDB else 1,
            )
        )
        return CandidateComparison(
            matches=results,
            prefiltered=len(candidates) - len(filtered),
            compared=compared,
            failed=len(filtered) - compared,
        )

    async def _server_active_art_url(
        self, item: MediaItem, art_type: ArtType, season_id: int | None
    ) -> str | None:
        """Return the art URL currently selected on the media server, if any.

        Raises:
            ValueError: When the server cannot be asked.
        """
        if item.id is None:
            return None
        try:
            server_id = await resolve_server_item_id(
                item.id,
                art_type,
                season_id,
                database=self._database,
                provider_registry=self.provider_registry,
            )
            if not server_id:
                return None
            return await self.provider_registry.fetch_server_active_art_url(
                server_id, art_type
            )
        except (httpx2.HTTPError, ValueError) as exc:
            logger.debug(
                "Could not read the media server's %s of item %s: %s",
                art_type,
                item.id,
                exc,
            )
            raise ValueError("Could not read media-server artwork selection") from exc

    async def _phash_from_remote_reference(
        self,
        item: MediaItem,
        art_type: ArtType,
        *,
        season_id: int | None,
        saved_url: str | None,
    ) -> tuple[str, MatchReference] | None:
        """Return a reference pHash from the server image, else the saved URL.

        Raises:
            ValueError: When the server cannot be asked or the image read.
        """
        server_active_url = await self._server_active_art_url(item, art_type, season_id)
        # A server with no selected image can use the saved URL as reference.
        # A failed server lookup is an error, not evidence that its image is absent.
        reference_url = server_active_url or saved_url
        if not reference_url:
            return None

        logger.debug(
            "Item %s has no local %s; matching against the %s",
            item.id,
            art_type,
            "media server's image" if server_active_url else "saved URL",
        )
        fingerprint = await self._cache.cached_url_phash(reference_url, fresh=True)
        if fingerprint is None:
            raise ValueError("Could not read remote artwork reference")
        return fingerprint, "media_server" if server_active_url else "saved_url"

    async def _match_against_candidates(
        self,
        item: MediaItem,
        season: Season | None,
        art_type: ArtType,
        *,
        include_overturedb: bool,
        reference_phash: str,
        reference_width: int,
        threshold: int,
    ) -> CandidateComparison:
        """Gather candidates under current settings and score them."""
        async with self._database.read_session() as session:
            policy = CandidatePolicy.of(await get_app_settings(session))
        sources = await self._candidates.gather(
            item,
            art_type,
            season_id=season.id if season else None,
            season_num=season.season_num if season else None,
            policy=policy,
            include_overturedb=include_overturedb,
        )
        comparison = await self.match_candidates(
            reference_phash,
            sources.flat(),
            threshold,
            reference_width=reference_width,
        )
        return replace(comparison, errors=sources.errors)

    async def identical_to_local(self, url: str, facts: ArtFileFacts) -> bool:
        """Return whether the original image at *url* is the local file's bytes.

        Raises:
            ValueError: When the image cannot be fetched or read.
        """
        try:
            return await remote_matches_file(url, facts, cache=self._cache)
        except (httpx2.HTTPError, OSError, ValueError) as exc:
            raise ValueError(
                f"could not compare with the local file: {public_error_message(exc)}"
            ) from exc

    async def match_item_art(
        self,
        item_id: int,
        art_type: ArtType,
        threshold: int = MATCH_THRESHOLD_DEFAULT,
        season_id: int | None = None,
        *,
        include_overturedb: bool,
        refresh: bool = True,
    ) -> ArtMatchOutcome:
        """Compare provider candidates with the slot's current reference image.

        The local file is the reference when there is one. Its recorded facts
        are refreshed first, so the comparison and the database agree on what
        is on disk; without a local file the media server's current image, then
        the saved URL, is used instead. A caller that has just refreshed the
        item passes ``refresh=False``.
        """

        if refresh:
            await self._local_assets.refresh_locked(
                item_id, source="art.match", themes=False
            )
        async with self._database.read_session() as session:
            target = await resolve_art_target(session, item_id, art_type, season_id)
            if target is None:
                return ArtMatchOutcome(
                    ArtMatchResponse(errors=["artwork target does not exist"])
                )
            item, season, target_obj = target
            slot = read_art_slot(target_obj, art_type)
        facts = art_file_facts(slot)

        reference: MatchReference
        if facts is not None:
            if facts.phash is None:
                return ArtMatchOutcome(
                    ArtMatchResponse(errors=["local artwork could not be decoded"])
                )
            reference_phash, reference = facts.phash, "local_file"
            reference_width = facts.width or 0
        else:
            try:
                remote = await self._phash_from_remote_reference(
                    item, art_type, season_id=season_id, saved_url=slot.url
                )
            except ValueError as exc:
                return ArtMatchOutcome(ArtMatchResponse(errors=[str(exc)]))
            if remote is None:
                return ArtMatchOutcome(
                    ArtMatchResponse(
                        reason="no local file, media-server image or saved URL "
                        "to compare against"
                    )
                )
            reference_phash, reference = remote
            reference_width = 0

        comparison = await self._match_against_candidates(
            item,
            season,
            art_type,
            include_overturedb=include_overturedb,
            reference_phash=reference_phash,
            reference_width=reference_width,
            threshold=threshold,
        )

        errors = list(comparison.errors)
        if facts is not None:
            errors.extend(
                await annotate_perfect_matches(
                    facts, comparison.matches, cache=self._cache
                )
            )

        return ArtMatchOutcome(
            ArtMatchResponse(
                # Python's sort is stable, so matches keep their distance order.
                matches=sorted(
                    comparison.matches, key=lambda match: not match.perfect_match
                ),
                total_compared=comparison.compared,
                prefiltered=comparison.prefiltered,
                failed=comparison.failed,
                errors=errors,
                reference=reference,
            ),
            local_file=facts,
        )
