"""Public dataset REST and WebSocket schemas."""

lazy from datetime import datetime
lazy from typing import Literal

lazy from pydantic import Field

lazy from ..domain import MediaType
lazy from .art import ArtCandidate
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope


class PublicDatasetEnabledRequest(StrictBaseModel):
    """Validate the public dataset enabled request payload."""

    enabled: bool


#: How the last catalog sync went.
type PublicDatasetSyncOutcome = Literal["never_synced", "success", "failed"]


class PublicDatasetSyncStats(StrictBaseModel):
    """What one catalog sync downloaded and imported."""

    entries: int = 0
    items: int = 0
    movies: int = 0
    shows: int = 0
    seasons: int = 0
    errors: int = 0
    catalog_url: str | None = None
    catalog_bytes: int = 0
    catalog_uncompressed_bytes: int = 0
    schema_version: int | None = None


class PublicDatasetStatus(StrictBaseModel):
    """Public dataset status response."""

    enabled: bool
    repo_url: str
    catalog_url: str
    last_synced_at: datetime | None = None
    last_status: PublicDatasetSyncOutcome = "never_synced"
    last_stats: PublicDatasetSyncStats | None = None
    next_run: str | None = None
    timezone: str


class PublicDatasetSyncEvent(JobEnvelope):
    """WebSocket payload for public dataset sync lifecycle events."""

    started_at: str | None = None
    finished_at: str | None = None
    stats: PublicDatasetSyncStats = Field(default_factory=PublicDatasetSyncStats)


class PublicDatasetSeasonSource(StrictBaseModel):
    """One public dataset season source."""

    season_num: int
    season_id: int | None = None
    poster_url: str
    candidate: ArtCandidate


class PublicDatasetSourcesItem(StrictBaseModel):
    """Item-level public dataset sources."""

    poster: list[ArtCandidate] = Field(default_factory=list[ArtCandidate])
    background: list[ArtCandidate] = Field(default_factory=list[ArtCandidate])
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None


class PublicDatasetSources(StrictBaseModel):
    """Public dataset sources response."""

    found: bool
    item: PublicDatasetSourcesItem | None = None
    seasons: list[PublicDatasetSeasonSource] = Field(
        default_factory=list[PublicDatasetSeasonSource]
    )


class PublicDatasetRecordItem(StrictBaseModel):
    """Persisted public dataset item record."""

    id: int | None = None
    media_type: MediaType
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    title: str | None = None
    year: int | None = None
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    catalog_synced_at: datetime | None = None


class PublicDatasetRecordSeason(StrictBaseModel):
    """Persisted public dataset season record."""

    id: int | None = None
    public_dataset_item_id: int
    season_num: int
    poster_url: str | None = None


class PublicDatasetRecord(StrictBaseModel):
    """Public dataset record response."""

    found: bool
    item: PublicDatasetRecordItem | None = None
    seasons: list[PublicDatasetRecordSeason] = Field(
        default_factory=list[PublicDatasetRecordSeason]
    )
