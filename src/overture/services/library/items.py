"""Shared media-item serialization and library websocket events."""

lazy from collections import defaultdict
lazy from collections.abc import Collection, Sequence

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...db.art_slots import find_art_slot
lazy from ...db.completion import holds_files
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetItem
lazy from ...db.models.season import Season
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import ArtType, AspectRatioTolerance, MediaType
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.library import (
    MediaItemRead,
    SeasonRead,
    media_item_read_from_model,
    season_read_from_model,
)
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import has_incorrect_aspect_ratio


def _public_dataset_complete(item: PublicDatasetItem) -> bool:
    return bool(item.poster_url and item.background_url and item.youtube_id_overturedb)


async def _public_dataset_status_item_ids(
    db: AsyncSession,
    items: Sequence[MediaItem],
    public_items: dict[int, PublicDatasetItem],
) -> tuple[set[int], set[int]]:
    themerrdb_item_ids = {
        item.id
        for item in items
        if item.id is not None
        and (public_item := public_items.get(item.id)) is not None
        and bool(public_item.youtube_id_themerrdb)
    }

    show_item_ids = [
        item.id for item in items if item.media_type == MediaType.SHOW and item.id
    ]
    local_seasons_by_item_id = await SeasonRepository(
        db
    ).tracked_season_nums_by_item_ids(show_item_ids)
    public_seasons_by_item_id = await PublicDatasetRepository(
        db
    ).season_posters_by_item_ids(
        {
            public_item.id
            for public_item in public_items.values()
            if public_item.id is not None and public_item.media_type == MediaType.SHOW
        }
    )

    complete_item_ids: set[int] = set()
    for item in items:
        if item.id is None:
            continue
        public_item = public_items.get(item.id)
        if not public_item or not _public_dataset_complete(public_item):
            continue
        if item.media_type == MediaType.SHOW:
            required_seasons = local_seasons_by_item_id.get(item.id, set())
            public_seasons = public_seasons_by_item_id.get(public_item.id or -1, {})
            if not required_seasons or not required_seasons.issubset(public_seasons):
                continue
        complete_item_ids.add(item.id)
    return complete_item_ids, themerrdb_item_ids


def _has_incorrect_aspect_ratio(
    item: MediaItem, seasons: list[Season], tolerance: AspectRatioTolerance
) -> bool:
    """Return whether the item's poster, background or a season poster is misshapen."""
    owners: list[tuple[MediaItem | Season, ArtType]] = [
        (item, ArtType.POSTER),
        (item, ArtType.BACKGROUND),
        *((season, ArtType.SEASON_POSTER) for season in seasons),
    ]
    # Stored slots only: an absent slot has no dimensions to check, and
    # read_art_slot would build a throwaway ORM row for it.
    slots = ((find_art_slot(owner, art_type), art_type) for owner, art_type in owners)
    return any(
        slot is not None
        and has_incorrect_aspect_ratio(slot.width, slot.height, art_type, tolerance)
        for slot, art_type in slots
    )


async def media_item_reads_with_public_dataset_status(
    db: AsyncSession,
    items: Sequence[MediaItem],
) -> list[MediaItemRead]:
    """Serialize media items using the nested asset shape returned
    by the library API."""
    if not items:
        return []

    # --- Batch-load settings once (needed for aspect-ratio tolerance) ---
    settings_row = await get_app_settings(db)
    tolerance = settings_row.aspect_ratio_tolerance

    # --- Batch-load seasons for all show items in one query ---
    show_ids = [
        item.id
        for item in items
        if item.media_type == MediaType.SHOW and item.id is not None
    ]
    seasons_by_item: defaultdict[int, list[Season]] = defaultdict(list)
    if show_ids:
        all_seasons = await SeasonRepository(db).list_tracked_for_items(show_ids)
        for season in all_seasons:
            seasons_by_item[season.media_item_id].append(season)

    public_items = await PublicDatasetRepository(db).items_by_media_item_id(items)
    complete_item_ids, themerrdb_item_ids = await _public_dataset_status_item_ids(
        db, items, public_items
    )

    collections = await CollectionRepository(db).collection_ids_by_item(
        [item.id for item in items if item.id is not None]
    )
    reads: list[MediaItemRead] = []
    for item in items:
        if item.id is None:
            continue

        seasons = seasons_by_item[item.id]
        public_item = public_items.get(item.id)
        reads.append(
            media_item_read_from_model(
                item,
                public_dataset_ids=PublicDatasetRepository.ids_agreement(
                    item, public_item
                ),
                public_dataset_complete=item.id in complete_item_ids,
                public_dataset_themerrdb=item.id in themerrdb_item_ids,
                library_collection_id=next(iter(collections.get(item.id, [])), None),
                seasons=seasons,
                has_incorrect_aspect_ratio=_has_incorrect_aspect_ratio(
                    item, seasons, tolerance
                ),
            )
        )

    return reads


def season_reads(item: MediaItem, seasons: Sequence[Season]) -> list[SeasonRead]:
    """Serialize the item's seasons with their poster assets."""
    files = holds_files(item)
    return [season_read_from_model(season, files=files) for season in seasons]


async def require_item(db: AsyncSession, item_id: int) -> MediaItem:
    """Return the media item, or raise the public 404 every caller wants."""
    item = await db.get(MediaItem, item_id)
    if not item:
        raise PublicServiceError(404, "Item not found")
    return item


async def emit_library_item_upserted(
    item_id: int,
    source: str,
    publisher: protocols.EventPublisher,
    *,
    database: Database,
) -> MediaItemRead | None:
    """Broadcast the item as it is stored now, or its removal once hidden.

    Returns:
        The broadcast item, or ``None`` when it is gone or hidden.
    """
    reads = await emit_library_items_upserted(
        [item_id], source, publisher, database=database
    )
    return reads[0] if reads else None


async def emit_library_items_upserted(
    item_ids: Collection[int],
    source: str,
    publisher: protocols.EventPublisher,
    *,
    database: Database,
) -> list[MediaItemRead]:
    """Broadcast each item as it is stored now, or its removal once hidden.

    The items are read afresh and together, so an event never carries a row a
    closed transaction left behind, and a batch costs the queries of one item.

    Returns:
        The broadcast items, without the removed ones.
    """
    if not item_ids:
        return []
    async with database.read_session() as db:
        items = (
            await db.exec(select(MediaItem).where(col(MediaItem.id).in_(item_ids)))
        ).all()
        removed = [item for item in items if item.server_removed_at is not None]
        reads = await media_item_reads_with_public_dataset_status(
            db, [item for item in items if item.server_removed_at is None]
        )

    for item in removed:
        if item.id is not None:
            await emit_library_item_removed(item.id, item.media_type, source, publisher)
    for read in reads:
        await publisher.broadcast(
            "library.item.upserted",
            {"item": read.model_dump(mode="json"), "source": source},
        )
    return reads


async def library_item_read(item_id: int, *, database: Database) -> MediaItemRead:
    """Return the item as the library API shows it.

    Raises:
        PublicServiceError: When the item does not exist.
    """
    async with database.read_session() as db:
        (read,) = await media_item_reads_with_public_dataset_status(
            db, [await require_item(db, item_id)]
        )
    return read


async def emit_library_item_removed(
    media_item_id: int,
    media_type: str,
    source: str,
    publisher: protocols.EventPublisher,
) -> None:
    """Broadcast removal from the visible library/sidebar."""
    await publisher.broadcast(
        "library.item.removed",
        {
            "media_item_id": media_item_id,
            "media_type": media_type,
            "source": source,
        },
    )
