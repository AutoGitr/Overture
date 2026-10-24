"""TMDB search, and items that exist only once their first asset is chosen.

A TMDB result opens like a library item before anything is stored. Its first
art or theme selection creates the media item - with its seasons, for a show -
and records the selection in one transaction, so a refused selection leaves no
row behind. The item has no local folder, so it records selections only.
"""

lazy import asyncio
lazy import logging
lazy from collections.abc import AsyncGenerator, Awaitable
lazy from contextlib import asynccontextmanager, nullcontext
lazy from typing import Literal

lazy import httpx2
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from .. import protocols
lazy from ..config import Settings
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..db.models.settings import get_app_settings
lazy from ..db.session import Database
lazy from ..domain import ArtType, CatalogMediaType, MediaType
lazy from ..integrations.tmdb import TMDBClient, TmdbDetails, TmdbTitle
lazy from ..repositories.media_items import MediaItemRepository
lazy from ..repositories.seasons import SeasonRepository
lazy from ..schemas.art import ArtSourcesResponse, SaveArtRequest
lazy from ..schemas.common import SaveSelectionResponse
lazy from ..schemas.library import ItemSelectionResponse
lazy from ..schemas.public_dataset import PublicDatasetSources
lazy from ..schemas.themes import SelectThemeRequest
lazy from ..schemas.tmdb import (
    TmdbCollectionResponse,
    TmdbItemPreview,
    TmdbSearchResponse,
    tmdb_collection_response,
    tmdb_collection_result,
    tmdb_item_preview,
    tmdb_item_result,
)
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.time import utc_now
lazy from .art.candidates import CandidatePolicy
lazy from .art.service import ArtService
lazy from .downloads.service import DownloadService
lazy from .library.items import (
    emit_library_item_upserted,
)
lazy from .public_dataset.browse import CatalogBrowser
lazy from .public_dataset.lookup import sources_for
lazy from .themes.service import ThemesService

logger = logging.getLogger(__name__)


def unsaved_item(details: TmdbDetails) -> MediaItem:
    """Return the media item a TMDB movie or show becomes, not yet stored."""
    return MediaItem(
        media_type=details.media_type,
        title=details.title,
        year=details.year,
        tmdb_id=details.tmdb_id,
        tvdb_id=details.tvdb_id,
        imdb_id=details.imdb_id,
    )


def _guids(details: TmdbDetails) -> dict[str, str]:
    """Return the external IDs that sync also matches stored items by."""
    guids = {"tmdb": str(details.tmdb_id)}
    if details.tvdb_id is not None:
        guids["tvdb"] = str(details.tvdb_id)
    if details.imdb_id is not None:
        guids["imdb"] = details.imdb_id
    return guids


def _season_num(
    details: TmdbDetails, art_type: ArtType, season_num: int | None
) -> int | None:
    """Return the slot's season number, refusing one the show does not have.

    Raises:
        PublicServiceError: When a season poster names no season of the show.
    """
    if not art_type.owned_by_season:
        return None
    if season_num not in {season.season_num for season in details.tracked_seasons}:
        raise PublicServiceError(
            400, f"{art_type.value} needs a season_num naming a season of this show"
        )
    return season_num


class TmdbItemsService:
    """Search TMDB and record the first selections of its movies and shows."""

    def __init__(
        self,
        *,
        app_config: Settings,
        database: Database,
        tmdb_client: TMDBClient,
        art: ArtService,
        themes: ThemesService,
        downloads: DownloadService,
        publisher: protocols.EventPublisher,
        catalog: CatalogBrowser,
    ) -> None:
        self._config = app_config
        self._database = database
        self._tmdb = tmdb_client
        self._art = art
        self._themes = themes
        self._downloads = downloads
        self._publisher = publisher
        self._catalog = catalog

    def _require_configured(self) -> None:
        """Refuse every TMDB request while no API key is set.

        Raises:
            PublicServiceError: When TMDB is not configured.
        """
        if not self._config.tmdb_configured:
            raise PublicServiceError(503, "TMDB is not configured.")

    @staticmethod
    async def _fetch[T](request: Awaitable[T]) -> T:
        """Await a TMDB request, reporting a failure without its details.

        Raises:
            PublicServiceError: When TMDB cannot be reached or answers badly.
        """
        try:
            return await request
        except httpx2.HTTPError as exc:
            logger.warning("TMDB request failed: %s", exc)
            raise PublicServiceError(502, "TMDB request failed.") from exc

    async def _details(self, media_type: MediaType, tmdb_id: int) -> TmdbDetails:
        """Return a movie or show from TMDB.

        Raises:
            PublicServiceError: When TMDB is unset, fails, or has no such title.
        """
        self._require_configured()
        details = await self._fetch(self._tmdb.get_details(media_type, tmdb_id))
        if details is None:
            raise PublicServiceError(404, f"TMDB has no {media_type.value} {tmdb_id}.")
        return details

    async def _title_search(
        self, media_type: MediaType, query: str
    ) -> tuple[tuple[TmdbTitle, ...], tuple[TmdbTitle, ...]]:
        """Return the titles, and for movies the collections, matching *query*."""
        if media_type != MediaType.MOVIE:
            return await self._tmdb.search("tv", query), ()
        items, collections = await asyncio.gather(
            self._tmdb.search("movie", query), self._tmdb.search("collection", query)
        )
        return items, collections

    async def _id_lookup(
        self, media_type: MediaType, tmdb_id: int
    ) -> tuple[tuple[TmdbTitle, ...], tuple[TmdbTitle, ...]]:
        """Return the title, and for movies the collection, with this TMDB ID."""
        if media_type == MediaType.MOVIE:
            details, collection = await asyncio.gather(
                self._tmdb.get_details(media_type, tmdb_id),
                self._tmdb.get_collection(tmdb_id),
            )
        else:
            details = await self._tmdb.get_details(media_type, tmdb_id)
            collection = None
        return (
            (details.summary,) if details else (),
            (collection.summary,) if collection else (),
        )

    async def search(self, media_type: MediaType, query: str) -> TmdbSearchResponse:
        """Search TMDB by title; a number also looks up that TMDB ID.

        A number can be an ID or a title ("1917"), so it is both: the ID's
        matches come first. Movies also find collections.
        """
        self._require_configured()
        query = query.strip()
        if not query:
            return TmdbSearchResponse(results=[])
        searches = [self._title_search(media_type, query)]
        if query.isdigit():
            searches.insert(0, self._id_lookup(media_type, int(query)))
        found = await self._fetch(asyncio.gather(*searches))
        # A title both searches find is listed once, where it first appears.
        items = {
            title.tmdb_id: title for titles, _collections in found for title in titles
        }
        collections = {
            title.tmdb_id: title
            for _titles, collections in found
            for title in collections
        }

        async with self._database.read_session() as db:
            existing = await MediaItemRepository(db).ids_by_tmdb_ids(
                media_type, set(items)
            )
        return TmdbSearchResponse(
            results=[
                *(
                    tmdb_item_result(media_type, item, existing.get(item.tmdb_id))
                    for item in items.values()
                ),
                *(
                    tmdb_collection_result(collection)
                    for collection in collections.values()
                ),
            ]
        )

    async def collection(
        self,
        collection_id: int,
        *,
        artwork_source: Literal["tmdb", "overturedb"] = "tmdb",
    ) -> TmdbCollectionResponse:
        """Return a TMDB collection's movies.

        Raises:
            PublicServiceError: When TMDB is unset, fails, or has no such
                collection.
        """
        self._require_configured()
        collection = await self._fetch(self._tmdb.get_collection(collection_id))
        if collection is None:
            raise PublicServiceError(404, f"TMDB has no collection {collection_id}.")
        async with self._database.read_session() as db:
            existing = await MediaItemRepository(db).ids_by_tmdb_ids(
                MediaType.MOVIE, {part.tmdb_id for part in collection.parts}
            )
        response = tmdb_collection_response(collection, existing)
        if artwork_source == "overturedb":
            catalog = await self._catalog.movie_artwork(
                {part.tmdb_id for part in collection.parts}
            )
            for member in response.items:
                entry = catalog.get(member.tmdb_id)
                member.poster_url = entry.poster_url if entry else None
                member.poster_preview_url = entry.poster_preview_url if entry else None
                member.catalog_entry_key = entry.entry_key if entry else None
                if entry:
                    member.title = entry.title
                    member.year = entry.year
        return response

    async def preview(self, media_type: MediaType, tmdb_id: int) -> TmdbItemPreview:
        """Describe a TMDB movie or show, naming the stored item it matches."""
        details = await self._details(media_type, tmdb_id)
        async with self._database.read_session() as db:
            existing = await MediaItemRepository(db).find_by_external_guids(
                _guids(details), media_type
            )
        return tmdb_item_preview(details, existing.id if existing else None)

    async def art_sources(
        self,
        media_type: MediaType | CatalogMediaType,
        tmdb_id: int,
        art_type: ArtType,
        season_num: int | None,
    ) -> ArtSourcesResponse:
        """Return artwork options for an unsaved item or catalog collection.

        Raises:
            PublicServiceError: When a collection requests a season poster.
        """
        if media_type == CatalogMediaType.COLLECTION:
            self._require_configured()
            if art_type.owned_by_season:
                raise PublicServiceError(422, "Collections have no season posters.")
            async with self._database.read_session() as session:
                policy = CandidatePolicy.of(await get_app_settings(session))
            candidates = await self._fetch(
                self._tmdb.art_candidates(
                    CatalogMediaType.COLLECTION,
                    tmdb_id,
                    art_type,
                    language_filter=policy.tmdb_language_filter,
                )
            )
            return ArtSourcesResponse(
                sources={
                    "tmdb": [
                        candidate
                        for candidate in candidates
                        if policy.accepts(candidate, art_type)
                    ]
                }
            )
        details = await self._details(MediaType(media_type), tmdb_id)
        return await self._art.sources_for(
            unsaved_item(details), art_type, _season_num(details, art_type, season_num)
        )

    async def public_dataset_sources(
        self, media_type: MediaType, tmdb_id: int
    ) -> PublicDatasetSources:
        """Return what OvertureDB holds for an unsaved item."""
        details = await self._details(media_type, tmdb_id)
        async with self._database.read_session() as db:
            return await sources_for(
                db, unsaved_item(details), [], app_config=self._config
            )

    @staticmethod
    async def _stored_item(db: AsyncSession, details: TmdbDetails) -> MediaItem:
        """Return the item these IDs name, creating it and its seasons if new."""
        existing = await MediaItemRepository(db).find_by_external_guids(
            _guids(details), details.media_type
        )
        if existing is not None:
            return existing
        item = unsaved_item(details)
        item.created_at = utc_now()
        db.add(item)
        await db.flush()
        if item.id is None:
            raise RuntimeError("A flushed item has an ID")
        db.add_all(
            Season(
                media_item_id=item.id, season_num=season.season_num, title=season.title
            )
            for season in details.tracked_seasons
        )
        await db.flush()
        return item

    @asynccontextmanager
    async def _storing(
        self, details: TmdbDetails
    ) -> AsyncGenerator[tuple[AsyncSession, MediaItem]]:
        """Yield a write session with the stored item, under its asset lock.

        A title not stored yet has no downloads to guard, so it takes no lock.
        Queued downloads start once the transaction commits.
        """
        async with self._database.read_session() as db:
            existing = await MediaItemRepository(db).find_by_external_guids(
                _guids(details), details.media_type
            )
        async with (
            self._downloads.asset_locks.acquire(existing.id)
            if existing is not None and existing.id is not None
            else nullcontext(),
            self._database.write_session() as db,
        ):
            yield db, await self._stored_item(db, details)
        await self._downloads.committed(db)

    async def _selection_response(
        self, item: MediaItem, source: str, job_id: str | None, *, created: bool
    ) -> ItemSelectionResponse:
        """Announce the item and return it with the selection's outcome."""
        read = (
            await emit_library_item_upserted(
                item.id, source, self._publisher, database=self._database
            )
            if item.id is not None
            else None
        )
        if read is None:
            raise PublicServiceError(404, "Item not found")
        return ItemSelectionResponse(
            selection=SaveSelectionResponse.of(job_id, created=created), item=read
        )

    async def save_art(
        self,
        media_type: MediaType,
        tmdb_id: int,
        art_type: ArtType,
        season_num: int | None,
        body: SaveArtRequest,
    ) -> ItemSelectionResponse:
        """Record a TMDB item's artwork, storing the item first if it is new."""
        details = await self._details(media_type, tmdb_id)
        slot_season = _season_num(details, art_type, season_num)
        selection = await self._art.prepare_selection(art_type, body)
        async with self._storing(details) as (db, item):
            target = (
                item
                if slot_season is None or item.id is None
                else (await SeasonRepository(db).map_by_number_for_item(item.id)).get(
                    slot_season
                )
            )
            if target is None:
                raise PublicServiceError(
                    400, f"The stored show has no season {slot_season}."
                )
            job_id, created = await self._art.record_selection(
                db, item, target, art_type, selection
            )
        return await self._selection_response(item, "tmdb.art", job_id, created=created)

    async def select_theme(
        self, media_type: MediaType, tmdb_id: int, body: SelectThemeRequest
    ) -> ItemSelectionResponse:
        """Record a TMDB item's theme, storing the item first if it is new."""
        details = await self._details(media_type, tmdb_id)
        metadata = await self._themes.video_metadata(body.youtube_id)
        async with self._storing(details) as (db, item):
            job_id, created = await self._themes.record_selection(
                db, item, body.youtube_id, metadata
            )
        return await self._selection_response(
            item, "tmdb.theme", job_id, created=created
        )
