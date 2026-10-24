"""Artwork candidates for one slot, from TMDB, the media server and OvertureDB.

The source picker and the matcher both read candidates through here, so they
offer and compare the same images under the same settings.
"""

lazy import asyncio
lazy import logging
lazy from collections.abc import Coroutine
lazy from dataclasses import dataclass, field
lazy from typing import Any, Self

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import AppSettings
lazy from ...db.session import Database
lazy from ...domain import (
    ArtSource,
    ArtType,
    AspectRatioTolerance,
    CatalogMediaType,
    TmdbLanguageFilter,
)
lazy from ...integrations.tmdb import TMDBClient
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.art import ArtCandidate
lazy from ...utils.errors import public_error_message
lazy from ...utils.image import is_valid_aspect_ratio, is_valid_image_format
lazy from ..public_dataset.lookup import build_candidate, get_art_candidates
lazy from ..public_dataset.schema.contract import art_source
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from ..server_identity import resolve_server_item_id

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CandidatePolicy:
    """The settings that decide which candidates are offered."""

    tmdb_language_filter: TmdbLanguageFilter
    aspect_ratio_tolerance: AspectRatioTolerance
    disable_media_server_art: bool
    skip_media_server_tmdb_urls: bool

    @classmethod
    def of(cls, settings: AppSettings) -> Self:
        """Return the policy the saved settings describe."""
        return cls(
            tmdb_language_filter=settings.tmdb_language_filter,
            aspect_ratio_tolerance=settings.aspect_ratio_tolerance,
            disable_media_server_art=settings.disable_media_server_art,
            skip_media_server_tmdb_urls=settings.skip_media_server_tmdb_urls,
        )

    def accepts(self, candidate: ArtCandidate, art_type: ArtType) -> bool:
        """Return whether a provider image has a usable format and shape."""
        return is_valid_image_format(candidate.url) and is_valid_aspect_ratio(
            candidate.width or 0,
            candidate.height or 0,
            art_type,
            self.aspect_ratio_tolerance,
        )


@dataclass(slots=True, frozen=True)
class CandidateSources:
    """Candidates by the source that offered them, and the sources that failed."""

    by_source: dict[str, list[ArtCandidate]] = field(
        default_factory=dict[str, list[ArtCandidate]]
    )
    errors: list[str] = field(default_factory=list[str])

    def flat(self) -> list[ArtCandidate]:
        """Return every candidate once, the first source offering a URL keeping it.

        TMDB comes first, so it sorts higher when match scores tie.
        """
        unique: dict[str, ArtCandidate] = {}
        for candidates in self.by_source.values():
            for candidate in candidates:
                unique.setdefault(candidate.url, candidate)
        return list(unique.values())


class ArtCandidates:
    """Read one slot's artwork options from every source, concurrently."""

    def __init__(
        self,
        *,
        database: Database,
        provider_registry: ProviderRegistry,
        tmdb_client: TMDBClient,
        app_config: Settings,
    ) -> None:
        self._database = database
        self._providers = provider_registry
        self._tmdb = tmdb_client
        self._app_config = app_config

    async def gather(
        self,
        item: MediaItem,
        art_type: ArtType,
        *,
        season_id: int | None,
        season_num: int | None,
        policy: CandidatePolicy,
        include_overturedb: bool,
    ) -> CandidateSources:
        """Return the slot's candidates; a failing source is reported and skipped.

        A season poster names its season by ID for the media server and by
        number for TMDB and OvertureDB. The media server is asked only about
        stored items, which it can hold.
        """
        lookups: dict[str, Coroutine[Any, Any, list[ArtCandidate]]] = {}
        if self._app_config.tmdb_configured and item.tmdb_id:
            lookups[ArtSource.TMDB] = self._tmdb_candidates(
                item, art_type, season_num, policy
            )
        if item.id is not None and not policy.disable_media_server_art:
            lookups[self._providers.provider.server_type] = self._server_candidates(
                item.id, art_type, season_id, policy
            )
        if include_overturedb:
            lookups[ArtSource.OVERTUREDB] = self._overturedb_candidates(
                item, art_type, season_num
            )
        return await self._resolve(item.title, lookups)

    async def _resolve(
        self, title: str, lookups: dict[str, Coroutine[Any, Any, list[ArtCandidate]]]
    ) -> CandidateSources:
        sources = CandidateSources()
        results = await asyncio.gather(*lookups.values(), return_exceptions=True)
        for name, result in zip(lookups, results, strict=True):
            if isinstance(result, httpx2.HTTPError | SQLAlchemyError | ValueError):
                # The source was asked, so it is listed, with nothing to offer.
                sources.by_source[name] = []
                sources.errors.append(
                    f"{name} artwork lookup failed: {public_error_message(result)}"
                )
                logger.warning("%s artwork for %s failed: %s", name, title, result)
            elif isinstance(result, BaseException):
                raise result
            else:
                sources.by_source[name] = result
        return sources

    async def _tmdb_candidates(
        self,
        item: MediaItem,
        art_type: ArtType,
        season_num: int | None,
        policy: CandidatePolicy,
    ) -> list[ArtCandidate]:
        if item.tmdb_id is None or (art_type.owned_by_season and season_num is None):
            return []
        candidates = await self._tmdb.art_candidates(
            item.media_type,
            item.tmdb_id,
            art_type,
            season_num=season_num,
            language_filter=policy.tmdb_language_filter,
        )
        return [c for c in candidates if policy.accepts(c, art_type)]

    async def _server_candidates(
        self,
        item_id: int,
        art_type: ArtType,
        season_id: int | None,
        policy: CandidatePolicy,
    ) -> list[ArtCandidate]:
        server_id = await resolve_server_item_id(
            item_id,
            art_type,
            season_id,
            database=self._database,
            provider_registry=self._providers,
        )
        if not server_id:
            return []
        return await self._server_art(server_id, art_type, policy)

    async def _server_art(
        self, server_id: str, art_type: ArtType, policy: CandidatePolicy
    ) -> list[ArtCandidate]:
        candidates = await self._providers.provider.get_art_candidates(
            server_id, art_type
        )
        accepted = [
            candidate
            for candidate in candidates
            if policy.accepts(candidate, art_type)
            and not (
                policy.skip_media_server_tmdb_urls
                and art_source(candidate.url) == ArtSource.TMDB
            )
        ]
        accepted.sort(key=lambda candidate: candidate.area, reverse=True)
        return accepted

    async def _overturedb_candidates(
        self, item: MediaItem, art_type: ArtType, season_num: int | None
    ) -> list[ArtCandidate]:
        """Return the catalog's curated artwork, which is offered as it is."""
        async with self._database.read_session() as session:
            return await get_art_candidates(
                session,
                item,
                art_type,
                season_num,
                app_config=self._app_config,
            )

    async def gather_collection(
        self, collection: MediaCollection, art_type: ArtType, policy: CandidatePolicy
    ) -> CandidateSources:
        """Use the same source policy, ordering and error handling for collections."""
        if collection.tmdb_collection_id is None:
            return CandidateSources()
        lookups: dict[str, Coroutine[Any, Any, list[ArtCandidate]]] = {}
        if self._app_config.tmdb_configured and collection.tmdb_collection_id:
            lookups[ArtSource.TMDB] = self._collection_tmdb(
                collection.tmdb_collection_id, art_type, policy
            )
        if not policy.disable_media_server_art:
            lookups[self._providers.provider.server_type] = self._server_art(
                collection.server_item_id, art_type, policy
            )
        lookups[ArtSource.OVERTUREDB] = self._collection_catalog(collection, art_type)
        return await self._resolve(collection.title, lookups)

    async def _collection_tmdb(
        self, tmdb_id: int, art_type: ArtType, policy: CandidatePolicy
    ) -> list[ArtCandidate]:
        return [
            candidate
            for candidate in await self._tmdb.art_candidates(
                CatalogMediaType.COLLECTION,
                tmdb_id,
                art_type,
                language_filter=policy.tmdb_language_filter,
            )
            if policy.accepts(candidate, art_type)
        ]

    async def _collection_catalog(
        self, collection: MediaCollection, art_type: ArtType
    ) -> list[ArtCandidate]:
        async with self._database.read_session() as session:
            schedule = await load_schedule(
                session, PUBLIC_DATASET_SCHEDULE, timezone=self._app_config.TZ
            )
            if not schedule.enabled or not collection.tmdb_collection_id:
                return []
            entries = await PublicDatasetRepository(session).collections_by_tmdb_id(
                {collection.tmdb_collection_id}
            )
            entry = entries.get(collection.tmdb_collection_id)
        url = (
            (
                entry.background_url
                if art_type is ArtType.BACKGROUND
                else entry.poster_url
            )
            if entry
            else None
        )
        candidate = build_candidate(url, art_type)
        return [candidate] if candidate else []
