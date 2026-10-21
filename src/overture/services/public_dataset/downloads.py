"""Queue OvertureDB downloads for local media items."""

lazy from dataclasses import dataclass
lazy from typing import Self

lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import (
    ITEM_ART_TYPES,
    ArtType,
    IncrementalThemeOrder,
)
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from .index import PublicDatasetIndex


@dataclass(slots=True)
class QueuedDownloads:
    """How many downloads a batch queued, and how many failed to queue."""

    art: int = 0
    themes: int = 0
    errors: int = 0

    def __iadd__(self, other: QueuedDownloads) -> Self:
        self.art += other.art
        self.themes += other.themes
        self.errors += other.errors
        return self

    @property
    def total(self) -> int:
        """Return how many downloads were queued."""
        return self.art + self.themes


def _art_targets(
    index: PublicDatasetIndex, item: MediaItem, seasons: list[Season]
) -> list[JobTarget]:
    """Return the catalog artwork of the item's slots without a local file.

    Polling only fills in missing files; it never replaces one, whatever its
    origin, and sync has refreshed these facts from disk just before.
    """
    if item.id is None:
        return []
    owners: list[tuple[MediaItem | Season, ArtType]] = [
        (item, art_type) for art_type in ITEM_ART_TYPES
    ]
    owners.extend((season, ArtType.SEASON_POSTER) for season in seasons)
    targets: list[JobTarget] = []
    for owner, art_type in owners:
        season = owner if isinstance(owner, Season) else None
        if read_art_slot(owner, art_type).file_hash is not None:
            continue
        if url := index.art_url(item, art_type, season=season):
            targets.append(
                JobTarget.art(
                    item.id, art_type, url, season_id=season.id if season else None
                )
            )
    return targets


async def _queue_item(
    session: AsyncSession,
    index: PublicDatasetIndex,
    item: MediaItem,
    seasons: list[Season],
    *,
    include_art: bool,
    theme_order: IncrementalThemeOrder,
    downloads: DownloadService,
) -> QueuedDownloads:
    """Queue OvertureDB downloads for one item's missing local files.

    A slot with a download already pending keeps it: the catalog only fills
    slots nothing else is filling.
    """
    queued = QueuedDownloads()
    if item.id is None:
        return queued
    if include_art:
        for target in _art_targets(index, item, seasons):
            _, created = await downloads.queue_job(session, target, supersede=False)
            queued.art += created
    if item.theme_file_hash is None and (
        youtube_id := index.youtube_id(item, theme_order.sources)
    ):
        _, created = await downloads.queue_job(
            session, JobTarget.theme(item.id, youtube_id), supersede=False
        )
        queued.themes += created
    return queued


async def queue_overturedb_downloads_for_items(
    item_ids: list[int],
    *,
    include_art: bool,
    theme_order: IncrementalThemeOrder = IncrementalThemeOrder.OFF,
    downloads: DownloadService,
    app_config: Settings,
    database: Database,
) -> QueuedDownloads:
    """Queue OvertureDB art/theme downloads for the supplied local item IDs.

    Each item is queued in a transaction of its own, so one that fails is
    counted and the rest still commit.
    """
    queued = QueuedDownloads()
    if not item_ids or (not include_art and theme_order is IncrementalThemeOrder.OFF):
        return queued

    async with database.read_session() as session:
        items = await MediaItemRepository(session).list_bulk_targets(
            item_ids=item_ids, include_unmonitored=True
        )
        index = await PublicDatasetIndex.build(session, items, app_config=app_config)

    for item in items:
        if item.id is None:
            continue
        try:
            async with (
                downloads.asset_locks.acquire(item.id),
                database.write_session() as session,
            ):
                current = await session.get(MediaItem, item.id)
                if current is None:
                    continue
                item_queued = await _queue_item(
                    session,
                    index,
                    current,
                    await SeasonRepository(session).list_tracked_for_item(item.id)
                    if include_art
                    else [],
                    include_art=include_art,
                    theme_order=theme_order,
                    downloads=downloads,
                )
        except SQLAlchemyError, ValueError:
            queued.errors += 1
            continue
        queued += item_queued
        await downloads.committed(session)
    return queued
