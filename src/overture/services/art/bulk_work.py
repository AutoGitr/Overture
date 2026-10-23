"""Work planning for bulk art matching.

:func:`plan_bulk_art` lists every (item, art type, season) slot in the run's
scope from the database alone and decides what it can without the disk;
:func:`load_art_batch` reads one batch of the remaining visits from disk and
the database just before they are visited.
"""

lazy from collections import defaultdict
lazy from contextlib import aclosing
lazy from dataclasses import dataclass, field

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import ArtBulkSource, ArtType, MediaType
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.bulk import BulkMatchArtRequest
lazy from ..bulk_common import AssetPlan, planned_outcome, scope_chunks
lazy from ..local_assets.service import LocalAssets
lazy from ..public_dataset.index import PublicDatasetIndex
lazy from .bulk_targets import last_checked_at, target_art_slot

BulkArtWorkItem = tuple[MediaItem, ArtType, Season | None]

#: One planned slot of an item: its art type and, for a season slot, the season.
type ArtTarget = tuple[ArtType, int | None]


@dataclass(frozen=True, slots=True)
class BulkArtWork:
    """One batch of slots to visit, and OvertureDB's rows for them."""

    targets: list[BulkArtWorkItem]
    public_index: PublicDatasetIndex = field(default_factory=PublicDatasetIndex.empty)


def split_art_types(
    art_types: list[ArtType],
) -> tuple[list[ArtType], list[ArtType]]:
    """Split requested art types into the item-owned and season-owned ones.

    Both keep the order results are listed in (poster, background), whatever
    order they were requested in.
    """
    known = [art_type for art_type in ArtType if art_type in art_types]
    return (
        [art_type for art_type in known if not art_type.owned_by_season],
        [art_type for art_type in known if art_type.owned_by_season],
    )


async def plan_bulk_art(
    params: BulkMatchArtRequest,
    *,
    app_config: Settings,
    database: Database,
    chunk: int = CHUNK_SIZE,
) -> AssetPlan[ArtTarget]:
    """Plan every slot in scope without reading a file or asking a source.

    Slots that :func:`planned_outcome` decides are only counted; the rest are
    kept as IDs for :func:`load_art_batch`.
    """
    item_art_types, season_art_types = split_art_types(params.art_types)
    dataset_only = all(source.catalog for source in params.source_order)
    plan = AssetPlan[ArtTarget]()
    async with aclosing(scope_chunks(params, database=database, chunk=chunk)) as chunks:
        async for session, items in chunks:
            show_ids = [
                item.id
                for item in items
                if item.media_type == MediaType.SHOW and item.id is not None
            ]
            seasons = (
                await SeasonRepository(session).list_tracked_for_items(
                    show_ids, ordered=True
                )
                if season_art_types and show_ids
                else []
            )
            index = (
                await PublicDatasetIndex.build(session, items, app_config=app_config)
                if dataset_only
                else None
            )
            seasons_by_item: defaultdict[int, list[Season]] = defaultdict(list)
            for season in seasons:
                seasons_by_item[season.media_item_id].append(season)

            for item in items:
                slots: list[tuple[ArtType, Season | None]] = [
                    (art_type, None) for art_type in item_art_types
                ]
                slots.extend(
                    (art_type, season)
                    for season in seasons_by_item[item.id or 0]
                    for art_type in season_art_types
                )
                visits: list[ArtTarget] = []
                for art_type, season in slots:
                    stored = target_art_slot(item, art_type, season=season)
                    decided = planned_outcome(
                        params,
                        saved=stored.url if stored else None,
                        last_checked=last_checked_at(item, art_type, season=season),
                        catalog=None
                        if index is None
                        else index.art(item, art_type, season=season),
                    )
                    if decided is None:
                        visits.append((art_type, season.id if season else None))
                    else:
                        plan.decide(decided)
                plan.visit(item, visits)
    return plan


async def load_art_batch(
    params: BulkMatchArtRequest,
    batch: dict[int, tuple[ArtTarget, ...]],
    *,
    local_assets: LocalAssets,
    app_config: Settings,
    database: Database,
) -> BulkArtWork:
    """Read one batch of planned visits from disk, then load their rows.

    The batch's local artwork is refreshed first, so every decision the runner
    makes is made against the files on disk.
    """
    item_ids = list(batch)
    await local_assets.reconcile(
        item_ids=item_ids, art=True, themes=False, source="assets.art"
    )
    async with database.read_session() as session:
        # The plan already applied the scope; a refresh that completed an item
        # may have unmonitored it, which does not take it out of this run.
        items = await MediaItemRepository(session).list_bulk_targets(
            item_ids=item_ids, include_unmonitored=True
        )
        season_owners = [
            item_id
            for item_id, targets in batch.items()
            if any(season_id is not None for _, season_id in targets)
        ]
        seasons = {
            season.id: season
            for season in await SeasonRepository(session).list_tracked_for_items(
                season_owners
            )
        }
        index = (
            await PublicDatasetIndex.build(session, items, app_config=app_config)
            if ArtBulkSource.OVERTUREDB in params.source_order
            else PublicDatasetIndex.empty()
        )
    targets: list[BulkArtWorkItem] = []
    for item in items:
        for art_type, season_id in batch.get(item.id or 0, ()):
            if season_id is None:
                targets.append((item, art_type, None))
            elif season := seasons.get(season_id):
                targets.append((item, art_type, season))
    return BulkArtWork(targets, index)
