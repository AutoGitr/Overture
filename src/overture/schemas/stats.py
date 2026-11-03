"""Stats REST schemas."""

lazy from pydantic import Field, computed_field

lazy from .base import StrictBaseModel


def _percentage(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


class LibraryStats(StrictBaseModel):
    """Media library totals and monitored counts.

    Collection counts are ``None`` when the media server could not list them.
    """

    total_movies: int = 0
    monitored_movies: int = 0
    unmonitored_movies: int = 0
    total_shows: int = 0
    monitored_shows: int = 0
    unmonitored_shows: int = 0
    total_seasons: int = 0
    seasons_with_episodes: int = 0
    total_collections: int | None = None
    monitored_collections: int | None = None


class Coverage(StrictBaseModel):
    """How many of some assets Overture holds locally and has matched."""

    total: int = 0
    local_files: int = 0
    matched_files: int = 0
    total_size_bytes: int = 0

    @computed_field
    @property
    def local_percentage(self) -> float:
        """Return the share of assets with a local file."""
        return _percentage(self.local_files, self.total)

    @computed_field
    @property
    def matched_percentage(self) -> float:
        """Return the share of assets with a selection and a local file."""
        return _percentage(self.matched_files, self.total)

    @computed_field
    @property
    def avg_size_bytes(self) -> int:
        """Return the average size of a local file."""
        return (
            round(self.total_size_bytes / self.local_files) if self.local_files else 0
        )

    def __add__(self, other: Coverage) -> Coverage:
        return Coverage(
            total=self.total + other.total,
            local_files=self.local_files + other.local_files,
            matched_files=self.matched_files + other.matched_files,
            total_size_bytes=self.total_size_bytes + other.total_size_bytes,
        )


class ArtTypeStats(StrictBaseModel):
    """Artwork breakdown across posters, backgrounds, and season posters."""

    poster: Coverage = Field(default_factory=Coverage)
    poster_movies: Coverage = Field(default_factory=Coverage)
    poster_shows: Coverage = Field(default_factory=Coverage)
    background: Coverage = Field(default_factory=Coverage)
    background_movies: Coverage = Field(default_factory=Coverage)
    background_shows: Coverage = Field(default_factory=Coverage)
    season_poster: Coverage = Field(default_factory=Coverage)
    overall: Coverage = Field(default_factory=Coverage)


class ThemeStats(StrictBaseModel):
    """Theme music breakdown across movies, shows, and collections.

    ``collections`` is ``None`` when the media server could not list them, and
    the overall figures then cover movies and shows only.
    """

    movies: Coverage = Field(default_factory=Coverage)
    shows: Coverage = Field(default_factory=Coverage)
    collections: Coverage | None = None
    overall: Coverage = Field(default_factory=Coverage)


class DatabaseTableCount(StrictBaseModel):
    """Row count for a single database table."""

    table_name: str
    description: str
    row_count: int


class DatabaseStats(StrictBaseModel):
    """SQLite database metrics and table row counts."""

    file_size_bytes: int = 0
    wal_size_bytes: int = 0
    total_size_bytes: int = 0
    page_size: int = 0
    page_count: int = 0
    freelist_count: int = 0
    free_size_bytes: int = 0
    tables: list[DatabaseTableCount] = Field(default_factory=list[DatabaseTableCount])


class BackupStats(StrictBaseModel):
    """Existing database backups summary."""

    total_backups: int = 0
    total_size_bytes: int = 0
    latest_backup_at: str | None = None


class StorageSummary(StrictBaseModel):
    """Storage footprint aggregated across all asset types and database."""

    artwork_size_bytes: int = 0
    themes_size_bytes: int = 0
    database_size_bytes: int = 0
    backups_size_bytes: int = 0
    total_footprint_bytes: int = 0


class StatsResponse(StrictBaseModel):
    """Full application statistics response."""

    library: LibraryStats
    art: ArtTypeStats
    themes: ThemeStats
    database: DatabaseStats
    backups: BackupStats
    storage: StorageSummary
    generated_at: str
