"""Collection REST and WebSocket schemas."""

lazy import hashlib
lazy from datetime import datetime
lazy from typing import Annotated, Self

lazy from pydantic import Field, field_validator, model_validator

lazy from ..config import API_PREFIX
lazy from ..db.completion import collection_theme_status
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.public_dataset import PublicDatasetCollection
lazy from ..domain import (
    AssetStatus,
    CollectionMatch,
    CollectionMode,
    CollectionOrder,
    CollectionPreset,
    MediaType,
    RuleSourceType,
    ServerType,
    SyncMode,
)
lazy from ..integrations.mdblist import mdblist_identifier
lazy from .base import StrictBaseModel
lazy from .common import StatusResponse
lazy from .library import MediaItemRead
lazy from .validators import YouTubeId


class CollectionRead(StrictBaseModel):
    """Media-server collection response."""

    id: int
    title: str
    summary: str | None = None
    sort_title: str | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder = CollectionOrder.RELEASE
    visible_home: bool = False
    thumb_url: str | None = None
    art_url: str | None = None
    child_count: int = 0
    media_type: MediaType
    library_id: str | None = None
    server_added_at: str | None = None
    server_type: ServerType
    server_link: str | None = None
    #: The media server holds a theme for the collection.
    has_theme: bool = False
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_status: AssetStatus = AssetStatus.MISSING
    monitored: bool = True
    tmdb_collection_id: int | None = None
    tmdb_match: CollectionMatch = CollectionMatch.AUTO
    #: The catalog has an OvertureDB theme for the collection's TMDB collection.
    public_dataset_complete: bool = False
    #: The catalog has a ThemerrDB theme for it.
    public_dataset_themerrdb: bool = False


class CollectionDetail(CollectionRead):
    """One collection with its members and what limits its theme."""

    members: list[MediaItemRead]
    rule: CollectionRuleRead | None = None
    #: Why a theme cannot be stored on this collection, if it cannot.
    theme_unavailable: str | None = None
    theme_writable: bool = False
    catalog_entry_key: str | None = None
    #: The catalog entry's title, when OvertureDB has the TMDB collection.
    catalog_title: str | None = None
    #: The catalog's theme candidates for the collection.
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None


class CollectionMatchRequest(StrictBaseModel):
    """Match a collection to a TMDB collection; ``None`` keeps it unmatched."""

    media_type: MediaType
    tmdb_collection_id: Annotated[int, Field(gt=0)] | None


class CollectionThemeStatusResponse(StrictBaseModel):
    """Collection theme status response."""

    has_theme: bool
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None


class SetCollectionThemeRequest(StrictBaseModel):
    """Validate the set collection theme request payload."""

    youtube_id: YouTubeId
    media_type: MediaType


class DeleteCollectionThemeResponse(StatusResponse):
    """Collection theme delete response."""

    has_theme: bool
    theme_status: AssetStatus


class CollectionThemeUpdatedEvent(StrictBaseModel):
    """Collection theme state update."""

    collection_id: int
    media_type: MediaType
    has_theme: bool
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_status: AssetStatus


def _collection_image_url(
    collection_id: int, image_type: str, server_url: str | None
) -> str | None:
    """Return Overture's route for a collection image the server has.

    ``t`` names the server's current image, so a replaced one is fetched anew
    instead of read from the browser's cache, without revealing the server URL.
    """
    if not server_url:
        return None
    version = hashlib.sha256(server_url.encode()).hexdigest()[:16]
    return f"{API_PREFIX}/collections/{collection_id}/image/{image_type}?t={version}"


def collection_read(
    row: MediaCollection, catalog: PublicDatasetCollection | None
) -> CollectionRead:
    """Map a stored collection and its catalog entry to public output."""
    has_theme = row.server_theme_id is not None or row.theme_file_hash is not None
    return CollectionRead(
        id=row.id or 0,
        title=row.title,
        summary=row.summary,
        sort_title=row.sort_title,
        collection_mode=row.collection_mode,
        order_type=row.order_type,
        visible_home=row.visible_home,
        thumb_url=_collection_image_url(row.id or 0, "poster", row.thumb_url),
        art_url=_collection_image_url(row.id or 0, "background", row.art_url),
        child_count=row.child_count,
        media_type=row.media_type,
        library_id=row.library_id,
        server_added_at=row.server_added_at.isoformat()
        if row.server_added_at
        else None,
        server_type=row.server_type,
        server_link=row.server_link,
        has_theme=has_theme,
        youtube_id=row.youtube_id,
        youtube_title=row.youtube_title,
        youtube_duration=row.youtube_duration,
        theme_status=collection_theme_status(
            server_has_theme=has_theme, youtube_id=row.youtube_id
        ),
        monitored=row.monitored,
        tmdb_collection_id=row.tmdb_collection_id,
        tmdb_match=row.tmdb_match,
        public_dataset_complete=bool(catalog and catalog.youtube_id_overturedb),
        public_dataset_themerrdb=bool(catalog and catalog.youtube_id_themerrdb),
    )


def collection_theme_status_response(
    collection: CollectionRead,
) -> CollectionThemeStatusResponse:
    """Project synchronized collection theme state."""
    return CollectionThemeStatusResponse(
        has_theme=collection.has_theme,
        youtube_id=collection.youtube_id,
        youtube_title=collection.youtube_title,
        youtube_duration=collection.youtube_duration,
    )


class BulkCollectionMonitorUpdate(StrictBaseModel):
    """Validate bulk collection monitor updates."""

    collection_ids: list[int]
    media_type: MediaType
    monitored: bool


class CollectionUpdatedEvent(StrictBaseModel):
    """A collection's match, membership or monitoring changed."""

    collection_id: int


class CollectionThemeSources(StrictBaseModel):
    """The catalog's theme candidates for a matched collection."""

    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None


class CollectionOptions(StrictBaseModel):
    """Editable collection metadata and server display options."""

    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=10000)] | None = None
    sort_title: Annotated[str, Field(max_length=200)] | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder = CollectionOrder.RELEASE
    visible_home: bool = False

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        """Reject titles that become empty on the media server."""
        if not value.strip():
            raise ValueError("A collection needs a title")
        return value.strip()


class CollectionCreate(CollectionOptions):
    """Create a collection in one selected library."""

    media_type: MediaType
    library_id: Annotated[str, Field(min_length=1, max_length=200)]
    member_ids: Annotated[
        list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=10000)
    ]


class CollectionMembersUpdate(StrictBaseModel):
    """Replace membership and optionally set its display order."""

    member_ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=10000)]
    order_type: CollectionOrder


class CollectionFilter(StrictBaseModel):
    """An intersection of filters over the current server library."""

    decade: Annotated[int, Field(ge=1800, le=3000, multiple_of=10)] | None = None
    studio: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    genre: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class CollectionRuleWrite(StrictBaseModel):
    """A dynamic source with nullable overrides of global defaults."""

    source_type: RuleSourceType
    source_identifier: Annotated[str, Field(max_length=500)] = ""
    filters: CollectionFilter = Field(default_factory=CollectionFilter)
    sync_mode: SyncMode | None = None
    minimum_items: Annotated[int, Field(ge=1, le=100)] | None = None
    delete_below_minimum: bool | None = None
    sync_interval_hours: Annotated[int, Field(ge=1, le=8760)] = 24
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """Accept identifiers, never arbitrary fetch URLs or credentials."""
        if self.source_type is RuleSourceType.TMDB:
            if (
                not self.source_identifier.isdecimal()
                or int(self.source_identifier) <= 0
            ):
                raise ValueError("A TMDB rule needs a positive collection ID")
        elif self.source_type is RuleSourceType.MDBLIST:
            self.source_identifier = mdblist_identifier(self.source_identifier)
        elif not self.filters.model_dump(exclude_none=True):
            raise ValueError("Choose at least one library filter")
        return self


class CollectionRuleRead(CollectionRuleWrite):
    """Saved rule with its most recent outcome."""

    last_synced_at: datetime | None = None
    last_error: str | None = None


class CollectionSyncResponse(StrictBaseModel):
    """What one rule run changed."""

    added: int = 0
    removed: int = 0
    skipped: bool = False
    deleted: bool = False


class CollectionGenerateRequest(StrictBaseModel):
    """Preview or generate collections from metadata already in the library."""

    media_type: MediaType
    library_id: Annotated[str, Field(min_length=1)]
    preset: CollectionPreset
    titles: Annotated[list[str], Field(max_length=100)] = Field(default_factory=list)


class CollectionPresetRead(StrictBaseModel):
    """A generator candidate with its matching library count."""

    title: str
    count: int
    filters: CollectionFilter


class CollectionGenerateResponse(StrictBaseModel):
    """Per-collection generator results; one failure leaves others intact."""

    created: list[int] = Field(default_factory=list[int])
    errors: dict[str, str] = Field(default_factory=dict)
