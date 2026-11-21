"""Application statistics service."""

lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any, cast

lazy from sqlmodel import case, col, func, select, text
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import Select

lazy from ...db.models.asset import Asset, AssetDelivery
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...db.tables import table_description, table_models, table_of
lazy from ...domain import AssetStatus, DeliveryChannel, MediaType, ServerAsset
lazy from ...schemas.collections import CollectionRead
lazy from ...schemas.stats import (
    ArtTypeStats,
    BackupStats,
    Coverage,
    DatabaseStats,
    DatabaseTableCount,
    ImageCacheStats,
    LibraryStats,
    StatsResponse,
    StorageSummary,
    ThemeStats,
)
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now_iso
lazy from ..backup.service import BackupService
lazy from ..collections.reader import CollectionReader
lazy from ..storage.image_cache import ImageCache

#: What one asset counts toward: its kind, and the owner's kind and media type.
type _AssetKey = tuple[ServerAsset, str, MediaType | None]


@dataclass(frozen=True, slots=True)
class _AssetCounts:
    """How many assets hold something somewhere, are complete, and their file bytes."""

    held: int = 0
    complete: int = 0
    size_bytes: int = 0


async def _asset_counts(
    session: AsyncSession, collection_ids: list[int]
) -> dict[_AssetKey, _AssetCounts]:
    """Count every asset of a title, season or listed collection in one query.

    An asset holds something once any of its deliveries has content seen at
    it; it is complete as its stored status says; its bytes are those of the
    files it was found as.
    """
    owner = case(
        (col(Asset.media_item_id).is_not(None), "item"),
        (col(Asset.season_id).is_not(None), "season"),
        else_="collection",
    )
    seen = col(AssetDelivery.observed_hash).is_not(None)
    held = (
        select(AssetDelivery.id)
        .where(col(AssetDelivery.asset_id) == col(Asset.id), seen)
        .exists()
    )
    size = (
        select(func.coalesce(func.sum(col(AssetDelivery.file_size)), 0))
        .where(
            col(AssetDelivery.asset_id) == col(Asset.id),
            seen,
            col(AssetDelivery.channel) == DeliveryChannel.FILE,
        )
        .scalar_subquery()
    )
    columns: list[Any] = [
        col(Asset.kind),
        owner,
        col(MediaItem.media_type),
        func.sum(case((held, 1), else_=0)),
        func.sum(case((col(Asset.status) == AssetStatus.COMPLETE, 1), else_=0)),
        func.sum(size),
    ]
    stmt = (
        cast("Select[Any]", select(*columns))
        .outerjoin(Season, col(Season.id) == col(Asset.season_id))
        .outerjoin(
            MediaItem,
            col(MediaItem.id)
            == func.coalesce(col(Asset.media_item_id), col(Season.media_item_id)),
        )
        .where(
            col(Asset.collection_id).is_(None)
            | col(Asset.collection_id).in_(collection_ids)
        )
        .group_by(col(Asset.kind), owner, col(MediaItem.media_type))
    )
    rows: list[tuple[str, str, str | None, int | None, int | None, int | None]] = [
        tuple(row) for row in (await session.exec(stmt)).all()
    ]
    return {
        (
            ServerAsset(kind),
            owner_kind,
            MediaType(media_type) if media_type else None,
        ): _AssetCounts(held or 0, complete or 0, size_bytes or 0)
        for kind, owner_kind, media_type, held, complete, size_bytes in rows
    }


def _coverage(total: int, *counts: _AssetCounts) -> Coverage:
    """Return the coverage of *total* assets from their counted groups."""
    return Coverage(
        total=total,
        local_files=sum(count.held for count in counts),
        matched_files=sum(count.complete for count in counts),
        total_size_bytes=sum(count.size_bytes for count in counts),
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
        image_cache: ImageCache,
        collections: CollectionReader,
    ) -> None:
        self._database = database
        self._backups = backups
        self._image_cache = image_cache
        self._collections_reader = collections

    async def _collections(self) -> list[CollectionRead] | None:
        """The synced collections, or ``None`` when the media server has none."""
        try:
            return await self._collections_reader.listed()
        except PublicServiceError:
            return None

    @staticmethod
    async def _library(
        session: AsyncSession, collections: list[CollectionRead] | None
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
            total_collections=None if collections is None else len(collections),
            monitored_collections=None
            if collections is None
            else sum(row.monitored for row in collections),
        )

    @staticmethod
    def _art(
        counts: dict[_AssetKey, _AssetCounts],
        library: LibraryStats,
        collections: list[CollectionRead] | None,
    ) -> ArtTypeStats:
        """Count artwork assets, those held and complete, and their bytes."""
        totals = {
            MediaType.MOVIE: library.total_movies,
            MediaType.SHOW: library.total_shows,
        }

        def of(
            kind: ServerAsset, owner: str, media_type: MediaType | None
        ) -> _AssetCounts:
            return counts.get((kind, owner, media_type), _AssetCounts())

        poster_movies, poster_shows, background_movies, background_shows = (
            _coverage(totals[media_type], of(kind, "item", media_type))
            for kind in (ServerAsset.POSTER, ServerAsset.BACKGROUND)
            for media_type in MediaType
        )
        season_poster = _coverage(
            library.total_seasons,
            of(ServerAsset.SEASON_POSTER, "season", MediaType.SHOW),
        )
        collection_art = (
            _coverage(
                len(collections) * 2,
                of(ServerAsset.POSTER, "collection", None),
                of(ServerAsset.BACKGROUND, "collection", None),
            )
            if collections is not None
            else None
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
            collections=collection_art,
            overall=poster
            + background
            + season_poster
            + (collection_art or Coverage()),
        )

    @staticmethod
    def _themes(
        counts: dict[_AssetKey, _AssetCounts],
        library: LibraryStats,
        collections: list[CollectionRead] | None,
    ) -> ThemeStats:
        """Count themes, the ones held somewhere and complete, and their bytes."""
        movies = _coverage(
            library.total_movies,
            counts.get((ServerAsset.THEME, "item", MediaType.MOVIE), _AssetCounts()),
        )
        shows = _coverage(
            library.total_shows,
            counts.get((ServerAsset.THEME, "item", MediaType.SHOW), _AssetCounts()),
        )
        collection_themes = (
            _coverage(
                len(collections),
                counts.get((ServerAsset.THEME, "collection", None), _AssetCounts()),
            )
            if collections is not None
            else None
        )
        return ThemeStats(
            movies=movies,
            shows=shows,
            collections=collection_themes,
            overall=movies + shows + (collection_themes or Coverage()),
        )

    @staticmethod
    async def _database_stats(
        session: AsyncSession, files: tuple[int, int]
    ) -> DatabaseStats:
        """Read SQLite PRAGMA information and table counts, beside *files*' sizes.

        *files* are the sizes of the database file and its write-ahead log.
        """
        conn = await session.connection()

        async def pragma(name: str, default: int) -> int:
            value = (await conn.execute(text(f"PRAGMA {name}"))).scalar()
            return value if isinstance(value, int) else default

        page_size = await pragma("page_size", 4096)
        page_count = await pragma("page_count", 0)
        freelist_count = await pragma("freelist_count", 0)

        models = table_models()
        # One statement for every table, so a new table costs no extra query.
        columns: list[Any] = [
            select(func.count()).select_from(model).scalar_subquery()
            for model in models
        ]
        counts: tuple[int, ...] = tuple(
            (await session.exec(cast("Select[Any]", select(*columns)))).one()
        )
        db_bytes, wal_bytes = files
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
                    table_name=table_of(model).name,
                    description=table_description(model),
                    row_count=row_count,
                )
                for model, row_count in zip(models, counts, strict=True)
            ],
        )

    async def get_stats(self) -> StatsResponse:
        """Gather and compute comprehensive statistics across all domain entities."""
        collections = await self._collections()
        files = await owned_thread(
            _get_db_file_sizes, self._database.engine.url.database
        )
        async with self._database.read_session() as session:
            library = await self._library(session, collections)
            counts = await _asset_counts(session, [row.id for row in collections or ()])
            art = self._art(counts, library, collections)
            themes = self._themes(counts, library, collections)
            database = await self._database_stats(session, files)

        backups = await owned_thread(self._backups.store.list_backups)
        backup_bytes = sum(b.size_bytes for b in backups)
        cached = await self._image_cache.usage()
        image_cache = ImageCacheStats(
            original_files=cached.originals.files,
            original_size_bytes=cached.originals.size_bytes,
            thumb_files=cached.thumbs.files,
            thumb_size_bytes=cached.thumbs.size_bytes,
            total_size_bytes=cached.originals.size_bytes + cached.thumbs.size_bytes,
        )
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
            image_cache=image_cache,
            storage=StorageSummary(
                artwork_size_bytes=art.overall.total_size_bytes,
                themes_size_bytes=themes.overall.total_size_bytes,
                image_cache_size_bytes=image_cache.total_size_bytes,
                uploads_size_bytes=cached.uploads.size_bytes,
                database_size_bytes=database.total_size_bytes,
                backups_size_bytes=backup_bytes,
                total_footprint_bytes=art.overall.total_size_bytes
                + themes.overall.total_size_bytes
                + image_cache.total_size_bytes
                + cached.uploads.size_bytes
                + database.total_size_bytes
                + backup_bytes,
            ),
            generated_at=utc_now_iso(),
        )
