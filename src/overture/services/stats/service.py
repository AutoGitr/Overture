"""Application statistics service."""

lazy from pathlib import Path
lazy from typing import Any

lazy from sqlmodel import case, col, func, select, text
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.completion import SLOT_COMPLETE, THEME_COMPLETE
lazy from ...db.models.art import ArtSlot
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import (
    PublicDatasetCollection,
    PublicDatasetDraft,
    PublicDatasetItem,
    PublicDatasetSeason,
)
lazy from ...db.models.saved_schedule import SavedSchedule
lazy from ...db.models.schedule import TaskSchedule
lazy from ...db.models.season import Season
lazy from ...db.models.settings import AppSettings
lazy from ...db.session import Database
lazy from ...domain import ITEM_ART_TYPES, ArtType, AssetStatus, MediaType
lazy from ...schemas.stats import (
    ArtTypeStats,
    BackupStats,
    Coverage,
    DatabaseStats,
    DatabaseTableCount,
    LibraryStats,
    StatsResponse,
    StorageSummary,
    ThemeStats,
)
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now_iso
lazy from ..backup.service import BackupService
lazy from ..collections.service import CollectionsService

#: Every table, with what its rows are, as the statistics list them.
TABLES: tuple[tuple[type[Any], str], ...] = (
    (MediaItem, "Movies and TV shows"),
    (Season, "Show seasons"),
    (ArtSlot, "Poster, background, and season artwork slots"),
    (MediaCollection, "Media-server collections"),
    (PublicDatasetItem, "OvertureDB curated items"),
    (PublicDatasetSeason, "OvertureDB curated seasons"),
    (PublicDatasetCollection, "OvertureDB curated collections"),
    (PublicDatasetDraft, "OvertureDB drafts awaiting contribution"),
    (DownloadJob, "Download queue history"),
    (SavedSchedule, "Saved sync and asset schedules"),
    (TaskSchedule, "Recurring task schedules"),
    (AppSettings, "Application configuration"),
)

_HAS_FILE = col(ArtSlot.file_hash).is_not(None)
#: Counts of local and of complete art slots in a grouped query.
_SLOT_COUNTS = (
    func.sum(case((_HAS_FILE, 1), else_=0)),
    func.sum(case((SLOT_COMPLETE, 1), else_=0)),
)
#: Bytes of the local files of art slots in a grouped query.
_SLOT_BYTES = func.sum(
    case((_HAS_FILE, func.coalesce(col(ArtSlot.file_size), 0)), else_=0)
)


def _get_db_file_sizes(db_path_str: str | None) -> tuple[int, int]:
    """Read database file and WAL file sizes on disk safely in a worker thread."""
    if not db_path_str or db_path_str.startswith(":memory:"):
        return 0, 0
    db_bytes = 0
    wal_bytes = 0
    try:
        db_path = Path(db_path_str)
        if db_path.is_file():
            db_bytes = db_path.stat().st_size
        wal_path = Path(f"{db_path_str}-wal")
        if wal_path.is_file():
            wal_bytes = wal_path.stat().st_size
    except OSError:
        pass
    return db_bytes, wal_bytes


class StatsService:
    """Aggregate statistics for media items, artwork, themes, database, and storage."""

    def __init__(
        self,
        *,
        database: Database,
        backups: BackupService,
        collections: CollectionsService,
    ) -> None:
        self._database = database
        self._backups = backups
        self._collections = collections

    async def _collection_themes(self) -> tuple[int, Coverage] | None:
        """Count the synced collections and their themes.

        Returns:
            How many collections are monitored, and their theme coverage, or
            ``None`` when the media server has no collections.
        """
        try:
            collections = [
                *await self._collections.list_collections(MediaType.MOVIE),
                *await self._collections.list_collections(MediaType.SHOW),
            ]
        except PublicServiceError:
            return None
        return sum(c.monitored for c in collections), Coverage(
            total=len(collections),
            local_files=sum(c.has_theme for c in collections),
            matched_files=sum(
                c.theme_status is AssetStatus.COMPLETE for c in collections
            ),
        )

    @staticmethod
    async def _library(
        session: AsyncSession, collections: tuple[int, Coverage] | None
    ) -> LibraryStats:
        """Count library items by type and monitoring, and their seasons."""
        counts = {
            (MediaType(media_type), bool(monitored)): count
            for media_type, monitored, count in await session.exec(
                select(
                    col(MediaItem.media_type), col(MediaItem.monitored), func.count()
                ).group_by(col(MediaItem.media_type), col(MediaItem.monitored))
            )
        }
        seasons, with_episodes = (
            await session.exec(
                select(
                    func.count(),
                    func.sum(case((col(Season.file_count) > 0, 1), else_=0)),
                )
            )
        ).one()
        monitored = {
            media_type: counts.get((media_type, True), 0) for media_type in MediaType
        }
        unmonitored = {
            media_type: counts.get((media_type, False), 0) for media_type in MediaType
        }
        return LibraryStats(
            total_movies=monitored[MediaType.MOVIE] + unmonitored[MediaType.MOVIE],
            monitored_movies=monitored[MediaType.MOVIE],
            unmonitored_movies=unmonitored[MediaType.MOVIE],
            total_shows=monitored[MediaType.SHOW] + unmonitored[MediaType.SHOW],
            monitored_shows=monitored[MediaType.SHOW],
            unmonitored_shows=unmonitored[MediaType.SHOW],
            total_seasons=seasons or 0,
            seasons_with_episodes=with_episodes or 0,
            total_collections=collections[1].total if collections else None,
            monitored_collections=collections[0] if collections else None,
        )

    @staticmethod
    async def _art(session: AsyncSession, library: LibraryStats) -> ArtTypeStats:
        """Count artwork slots, their local files and matches, and their bytes."""
        owner = (col(ArtSlot.art_type), col(MediaItem.media_type))
        item_slots = col(ArtSlot.media_item_id) == col(MediaItem.id)
        counts = {
            (ArtType(art_type), MediaType(media_type)): (local or 0, matched or 0)
            for art_type, media_type, local, matched in await session.exec(
                select(*owner, *_SLOT_COUNTS)
                .join(MediaItem, item_slots)
                .group_by(*owner)
            )
        }
        sizes = {
            (ArtType(art_type), MediaType(media_type)): size or 0
            for art_type, media_type, size in await session.exec(
                select(*owner, _SLOT_BYTES).join(MediaItem, item_slots).group_by(*owner)
            )
        }
        # SLOT_COMPLETE reads the owning item, so each season joins it.
        season_local, season_matched, season_bytes = (
            await session.exec(
                select(*_SLOT_COUNTS, _SLOT_BYTES)
                .select_from(ArtSlot)
                .join(Season, col(ArtSlot.season_id) == col(Season.id))
                .join(MediaItem, col(Season.media_item_id) == col(MediaItem.id))
            )
        ).one()
        totals = {
            MediaType.MOVIE: library.total_movies,
            MediaType.SHOW: library.total_shows,
        }

        def coverage(art_type: ArtType, media_type: MediaType) -> Coverage:
            local, matched = counts.get((art_type, media_type), (0, 0))
            return Coverage(
                total=totals[media_type],
                local_files=local,
                matched_files=matched,
                total_size_bytes=sizes.get((art_type, media_type), 0),
            )

        poster_movies, poster_shows, background_movies, background_shows = (
            coverage(art_type, media_type)
            for art_type in ITEM_ART_TYPES
            for media_type in MediaType
        )
        season_poster = Coverage(
            total=library.total_seasons,
            local_files=season_local or 0,
            matched_files=season_matched or 0,
            total_size_bytes=season_bytes or 0,
        )
        poster = poster_movies + poster_shows
        background = background_movies + background_shows
        return ArtTypeStats(
            poster=poster,
            poster_movies=poster_movies,
            poster_shows=poster_shows,
            background=background,
            background_movies=background_movies,
            background_shows=background_shows,
            season_poster=season_poster,
            overall=poster + background + season_poster,
        )

    @staticmethod
    async def _themes(
        session: AsyncSession,
        library: LibraryStats,
        collections: tuple[int, Coverage] | None,
    ) -> ThemeStats:
        """Count item themes, their local files and matches, and their bytes."""
        has_file = col(MediaItem.theme_file_hash).is_not(None)
        theme_bytes = func.coalesce(col(MediaItem.theme_file_size), 0)
        rows = {
            MediaType(media_type): (local or 0, matched or 0, size or 0)
            for media_type, local, matched, size in await session.exec(
                select(
                    col(MediaItem.media_type),
                    func.sum(case((has_file, 1), else_=0)),
                    func.sum(case((THEME_COMPLETE, 1), else_=0)),
                    func.sum(case((has_file, theme_bytes), else_=0)),
                ).group_by(col(MediaItem.media_type))
            )
        }
        totals = {
            MediaType.MOVIE: library.total_movies,
            MediaType.SHOW: library.total_shows,
        }

        def coverage(media_type: MediaType) -> Coverage:
            local, matched, size = rows.get(media_type, (0, 0, 0))
            return Coverage(
                total=totals[media_type],
                local_files=local,
                matched_files=matched,
                total_size_bytes=size,
            )

        movies, shows = coverage(MediaType.MOVIE), coverage(MediaType.SHOW)
        collection_themes = collections[1] if collections else None
        return ThemeStats(
            movies=movies,
            shows=shows,
            collections=collection_themes,
            overall=movies + shows + (collection_themes or Coverage()),
        )

    async def _database_stats(self, session: AsyncSession) -> DatabaseStats:
        """Read SQLite PRAGMA information, file sizes, and table counts."""
        conn = await session.connection()

        async def pragma(name: str, default: int) -> int:
            value = (await conn.execute(text(f"PRAGMA {name}"))).scalar()
            return value if isinstance(value, int) else default

        page_size = await pragma("page_size", 4096)
        page_count = await pragma("page_count", 0)
        freelist_count = await pragma("freelist_count", 0)

        db_bytes, wal_bytes = await owned_thread(
            _get_db_file_sizes, self._database.engine.url.database
        )
        if db_bytes == 0 and page_count > 0:
            db_bytes = page_count * page_size

        return DatabaseStats(
            file_size_bytes=db_bytes,
            wal_size_bytes=wal_bytes,
            total_size_bytes=db_bytes + wal_bytes,
            page_size=page_size,
            page_count=page_count,
            freelist_count=freelist_count,
            free_size_bytes=freelist_count * page_size,
            tables=[
                DatabaseTableCount(
                    table_name=model.__tablename__,
                    description=description,
                    row_count=(
                        await session.exec(select(func.count()).select_from(model))
                    ).one(),
                )
                for model, description in TABLES
            ],
        )

    async def get_stats(self) -> StatsResponse:
        """Gather and compute comprehensive statistics across all domain entities."""
        collections = await self._collection_themes()
        async with self._database.read_session() as session:
            library = await self._library(session, collections)
            art = await self._art(session, library)
            themes = await self._themes(session, library, collections)
            database = await self._database_stats(session)

        backups = await owned_thread(self._backups.store.list_backups)
        backup_bytes = sum(b.size_bytes for b in backups)
        return StatsResponse(
            library=library,
            art=art,
            themes=themes,
            database=database,
            backups=BackupStats(
                total_backups=len(backups),
                total_size_bytes=backup_bytes,
                latest_backup_at=backups[0].created_at if backups else None,
            ),
            storage=StorageSummary(
                artwork_size_bytes=art.overall.total_size_bytes,
                themes_size_bytes=themes.overall.total_size_bytes,
                database_size_bytes=database.total_size_bytes,
                backups_size_bytes=backup_bytes,
                total_footprint_bytes=art.overall.total_size_bytes
                + themes.overall.total_size_bytes
                + database.total_size_bytes
                + backup_bytes,
            ),
            generated_at=utc_now_iso(),
        )
