"""Catalog REST and WebSocket schemas."""

lazy from datetime import datetime
lazy from typing import Annotated, Literal

lazy from pydantic import Field

lazy from ..domain import CatalogMediaType, MediaType
lazy from .art import ArtCandidate
lazy from .base import PublicText, StrictBaseModel
lazy from .common import JobEnvelope


class CatalogEnabledRequest(StrictBaseModel):
    """Validate the catalog enabled request payload."""

    enabled: bool


#: How the last catalog sync went.
type CatalogSyncOutcome = Literal["never_synced", "success", "failed"]


class CatalogSyncStats(StrictBaseModel):
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


class CatalogStatus(StrictBaseModel):
    """Catalog status response."""

    enabled: bool
    repo_url: str
    catalog_url: str
    last_synced_at: datetime | None = None
    last_status: CatalogSyncOutcome = "never_synced"
    last_stats: CatalogSyncStats | None = None
    next_run: str | None = None
    timezone: str


class CatalogSyncEvent(JobEnvelope):
    """WebSocket payload for catalog sync lifecycle events."""

    started_at: str | None = None
    finished_at: str | None = None
    stats: CatalogSyncStats = Field(default_factory=CatalogSyncStats)


class CatalogSeasonSource(StrictBaseModel):
    """One catalog season source."""

    season_num: int
    season_id: int | None = None
    poster_url: str
    candidate: ArtCandidate


class CatalogSourcesItem(StrictBaseModel):
    """Item-level catalog sources."""

    poster: list[ArtCandidate] = Field(default_factory=list[ArtCandidate])
    background: list[ArtCandidate] = Field(default_factory=list[ArtCandidate])
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    #: The catalog entry's name, which its drafts are saved under.
    entry_key: str | None = None


class CatalogSources(StrictBaseModel):
    """Catalog sources response."""

    found: bool
    item: CatalogSourcesItem | None = None
    seasons: list[CatalogSeasonSource] = Field(
        default_factory=list[CatalogSeasonSource]
    )


class CatalogRecordItem(StrictBaseModel):
    """Persisted catalog item record."""

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


class CatalogRecordSeason(StrictBaseModel):
    """Persisted catalog season record."""

    id: int | None = None
    catalog_item_id: int
    season_num: int
    poster_url: str | None = None


class CatalogRecordCollection(StrictBaseModel):
    """Persisted catalog collection record."""

    id: int | None = None
    tmdb_id: int
    title: str
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    no_theme: bool = False
    catalog_synced_at: datetime | None = None


class CatalogRecord(StrictBaseModel):
    """Catalog record response."""

    found: bool
    item: CatalogRecordItem | None = None
    collection: CatalogRecordCollection | None = None
    seasons: list[CatalogRecordSeason] = Field(
        default_factory=list[CatalogRecordSeason]
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


class ContributionIssue(StrictBaseModel):
    """A prefilled OvertureDB issue contributing one entry, or why there is none."""

    url: str | None = None
    reason: PublicText | None = None
    #: What the issue leaves out or the contributor still has to do on the form.
    notes: list[PublicText] = Field(default_factory=list[PublicText])


class CatalogEntryDetail(StrictBaseModel):
    """One catalog entry with the local draft of changes to it."""

    entry_key: str
    entry: CatalogEntry
    draft: CatalogEntry | None = None
    #: The issue contributing the draft, while there is one.
    draft_issue: ContributionIssue | None = None
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
    """How many named entries had their draft discarded."""

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
