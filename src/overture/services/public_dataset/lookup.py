"""Public-dataset candidate and record lookup from the local database."""

lazy from collections.abc import Sequence

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ArtType, CatalogMediaType, MediaType
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.art import ArtCandidate
lazy from ...schemas.public_dataset import (
    PublicDatasetRecord,
    PublicDatasetRecordCollection,
    PublicDatasetRecordItem,
    PublicDatasetRecordSeason,
    PublicDatasetSeasonSource,
    PublicDatasetSources,
    PublicDatasetSourcesItem,
)
lazy from ...utils.art_urls import art_preview_url, art_source_label
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from .index import PublicDatasetIndex, catalog_art_url
lazy from .schema.contract import (
    IDENTITY_FIELDS,
    entry_file_stem,
    parse_entry_file_stem,
)


def build_candidate(url: str | None, art_type: ArtType) -> ArtCandidate | None:
    """Build a public-dataset artwork candidate."""
    if not url:
        return None
    return ArtCandidate(
        url=url,
        preview_url=art_preview_url(url, art_type),
        source=art_source_label(url),
        title="OvertureDB",
        art_type=art_type,
    )


async def find_public_item(
    session: AsyncSession,
    item: MediaItem,
) -> PublicDatasetItem | None:
    """Return the matching public-dataset row for a stored or unsaved item."""
    return (await PublicDatasetRepository(session).match_items([item]))[0]


def art_candidates(
    index: PublicDatasetIndex,
    item: MediaItem,
    art_type: ArtType,
    *,
    season: Season | None = None,
) -> list[ArtCandidate]:
    """Return the dataset's candidate for one art slot from a built index."""
    candidate = build_candidate(index.art_url(item, art_type, season=season), art_type)
    return [candidate] if candidate else []


async def get_art_candidates(
    session: AsyncSession,
    item: MediaItem,
    art_type: ArtType,
    season_num: int | None = None,
    *,
    app_config: Settings,
) -> list[ArtCandidate]:
    """Return public-dataset art candidates for one stored or unsaved item.

    Returns an empty list when the dataset is disabled or no entry is found.
    Callers walking several items should build one
    :class:`~overture.services.public_dataset.index.PublicDatasetIndex` for the
    whole batch and read it with :func:`art_candidates` instead.
    """
    if not await _enabled(session, app_config=app_config):
        return []
    public_item = await find_public_item(session, item)
    if public_item is None or public_item.id is None:
        return []
    season_posters = (
        await PublicDatasetRepository(session).season_posters_by_item_ids(
            {public_item.id}
        )
        if art_type.owned_by_season
        else {}
    )
    candidate = build_candidate(
        catalog_art_url(
            public_item, season_posters.get(public_item.id, {}), art_type, season_num
        ),
        art_type,
    )
    return [candidate] if candidate else []


async def _enabled(session: AsyncSession, *, app_config: Settings) -> bool:
    """Return whether the public dataset is switched on."""
    schedule = await load_schedule(
        session, PUBLIC_DATASET_SCHEDULE, timezone=app_config.TZ
    )
    return schedule.enabled


async def get_sources_for_item(
    item_id: int, *, app_config: Settings, database: Database
) -> PublicDatasetSources:
    """Return available public-dataset art sources for a local media item.

    Nothing is found when the dataset is disabled or holds no entry.
    """
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        if not item:
            return PublicDatasetSources(found=False)
        return await sources_for(
            session,
            item,
            await SeasonRepository(session).list_for_item(item_id),
            app_config=app_config,
        )


async def sources_for(
    session: AsyncSession,
    item: MediaItem,
    local_seasons: Sequence[Season],
    *,
    app_config: Settings,
) -> PublicDatasetSources:
    """Return the public-dataset sources for a stored or unsaved item.

    *local_seasons* give each season candidate its ``season_id``.
    """
    if not await _enabled(session, app_config=app_config):
        return PublicDatasetSources(found=False)

    public_item = await find_public_item(session, item)
    if not public_item or public_item.id is None:
        return PublicDatasetSources(found=False)

    seasons = await PublicDatasetRepository(session).list_seasons(public_item.id)
    season_ids_by_num = {s.season_num: s.id for s in local_seasons}
    poster = build_candidate(public_item.poster_url, ArtType.POSTER)
    background = build_candidate(public_item.background_url, ArtType.BACKGROUND)

    return PublicDatasetSources(
        found=True,
        item=PublicDatasetSourcesItem(
            poster=[poster] if poster else [],
            background=[background] if background else [],
            youtube_id_overturedb=public_item.youtube_id_overturedb,
            youtube_id_themerrdb=public_item.youtube_id_themerrdb,
            entry_key=entry_file_stem(
                public_item.model_dump(include=set(IDENTITY_FIELDS))
            ),
        ),
        seasons=[
            PublicDatasetSeasonSource(
                season_num=season.season_num,
                season_id=season_ids_by_num.get(season.season_num),
                poster_url=season.poster_url,
                candidate=candidate,
            )
            for season in seasons
            if season.poster_url
            and (candidate := build_candidate(season.poster_url, ArtType.SEASON_POSTER))
        ],
    )


async def get_record_for_item(
    item_id: int, *, database: Database
) -> PublicDatasetRecord:
    """Return the public-dataset DB rows for a local media item, if any."""
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        if not item:
            return PublicDatasetRecord(found=False)
        return await _item_record(session, await find_public_item(session, item))


async def _item_record(
    session: AsyncSession, public_item: PublicDatasetItem | None
) -> PublicDatasetRecord:
    if public_item is None or public_item.id is None:
        return PublicDatasetRecord(found=False)
    seasons = await PublicDatasetRepository(session).list_seasons(public_item.id)
    return PublicDatasetRecord(
        found=True,
        item=PublicDatasetRecordItem.model_validate(public_item),
        seasons=[PublicDatasetRecordSeason.model_validate(s) for s in seasons],
    )


async def _collection_record(
    session: AsyncSession, tmdb_id: int | None
) -> PublicDatasetRecord:
    found = (
        await PublicDatasetRepository(session).collections_by_tmdb_id({tmdb_id})
        if tmdb_id is not None
        else {}
    )
    if not found:
        return PublicDatasetRecord(found=False)
    return PublicDatasetRecord(
        found=True,
        collection=PublicDatasetRecordCollection.model_validate(
            next(iter(found.values()))
        ),
    )


async def get_record_for_collection(
    collection_id: int, *, database: Database
) -> PublicDatasetRecord:
    """Return the catalog row for a library collection's TMDB collection, if any."""
    async with database.read_session() as session:
        row = await session.get(MediaCollection, collection_id)
        return await _collection_record(
            session, row.tmdb_collection_id if row is not None else None
        )


async def get_record_for_entry(
    media_type: CatalogMediaType, entry_key: str, *, database: Database
) -> PublicDatasetRecord:
    """Return the catalog rows an entry name identifies, if any."""
    try:
        field, value = parse_entry_file_stem(entry_key)
    except ValueError:
        return PublicDatasetRecord(found=False)
    async with database.read_session() as session:
        if media_type is CatalogMediaType.COLLECTION:
            tmdb_id = value if field == "tmdb_id" and isinstance(value, int) else None
            return await _collection_record(session, tmdb_id)
        public_item = await PublicDatasetRepository(session).find_item(
            MediaType(media_type), field, value
        )
        return await _item_record(session, public_item)
