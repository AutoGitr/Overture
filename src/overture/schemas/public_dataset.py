"""Public dataset REST and WebSocket schemas."""

lazy from datetime import datetime
lazy from typing import Annotated, Literal

lazy from pydantic import Field

lazy from ..domain import CatalogMediaType, MediaType
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
    collections: int = 0
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
    #: The catalog entry's name, which its drafts are saved under.
    entry_key: str | None = None


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
    no_theme: bool = False
    catalog_synced_at: datetime | None = None


class PublicDatasetRecordSeason(StrictBaseModel):
    """Persisted public dataset season record."""

    id: int | None = None
    public_dataset_item_id: int
    season_num: int
    poster_url: str | None = None


class PublicDatasetRecordCollection(StrictBaseModel):
    """Persisted public dataset collection record."""

    id: int | None = None
    tmdb_id: int
    title: str
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    no_theme: bool = False
    catalog_synced_at: datetime | None = None


class PublicDatasetRecord(StrictBaseModel):
    """Public dataset record response."""

    found: bool
    item: PublicDatasetRecordItem | None = None
    collection: PublicDatasetRecordCollection | None = None
    seasons: list[PublicDatasetRecordSeason] = Field(
        default_factory=list[PublicDatasetRecordSeason]
    )


class CatalogSeason(StrictBaseModel):
    """One season poster of a catalog entry."""

    season_num: Annotated[int, Field(ge=0)]
    poster_url: str


class CatalogEntry(StrictBaseModel):
    """A catalog entry; fields its media type does not carry are ``None``."""

    media_type: CatalogMediaType
    title: str
    year: int | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    #: OvertureDB says the title has no theme music.
    no_theme: bool = False
    seasons: list[CatalogSeason] | None = None


class CatalogEntryRow(StrictBaseModel):
    """One catalog entry as the catalog view lists it."""

    entry_key: str
    media_type: CatalogMediaType
    title: str
    year: int | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    poster_url: str | None = None
    #: A smaller rendition of the poster, when its source serves one.
    poster_preview_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    #: OvertureDB says the title has no theme music.
    no_theme: bool = False
    #: Season posters the entry holds; shows only.
    season_posters: int = 0
    has_draft: bool = False
    #: The library item or collection the entry describes, if there is one.
    library_item_id: int | None = None
    library_collection_id: int | None = None


class CatalogEntryDetail(StrictBaseModel):
    """One catalog entry with the local draft of changes to it."""

    entry_key: str
    entry: CatalogEntry
    draft: CatalogEntry | None = None
    library_item_id: int | None = None
    library_collection_id: int | None = None


class CatalogCounts(StrictBaseModel):
    """Catalog and draft counts without downloading the catalog."""

    movies: int
    shows: int
    collections: int
    drafts: int


class CatalogDraftsDiscard(StrictBaseModel):
    """The entries whose drafts to discard, by entry name."""

    entry_keys: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]],
        Field(min_length=1, max_length=5000),
    ]


class CatalogDraftsDiscarded(StrictBaseModel):
    """How many of the named entries had a draft that is now gone."""

    discarded: int


class CatalogDraftUpdate(StrictBaseModel):
    """Changes to a catalog entry; only the fields sent are changed."""

    title: str | None = None
    year: int | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    #: True flags the title as having no theme; False clears the flag.
    no_theme: bool | None = None
    seasons: list[CatalogSeason] | None = None
