"""Collection REST and WebSocket schemas."""

lazy import hashlib
lazy from datetime import datetime
lazy from typing import Annotated, Literal, Self

lazy from pydantic import Field, TypeAdapter, field_validator, model_validator

lazy from ..config import API_PREFIX
lazy from ..db.art_slots import read_art_slot
lazy from ..db.completion import collection_art_completion, collection_theme_status
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.public_dataset import PublicDatasetCollection
lazy from ..domain import (
    ArtType,
    AssetStatus,
    BuilderType,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    CollectionPreset,
    FilterField,
    FilterOperator,
    MediaType,
    RuleSourceType,
    ServerType,
    SmartSortOrder,
    SyncMode,
    TmdbPersonRole,
)
lazy from ..integrations.mdblist import mdblist_identifier
lazy from ..utils.collection_formats import (
    SeasonalDate,
    SortTitleFormat,
    SummaryFormat,
)
lazy from .base import StrictBaseModel
lazy from .common import StatusResponse
lazy from .library import MediaItemRead
lazy from .validators import YouTubeId


class ArrTagRead(StrictBaseModel):
    """One tag configured on Radarr or Sonarr."""

    id: int
    label: str


class FilterCondition(StrictBaseModel):
    """One atomic library or smart-collection filter condition."""

    field: FilterField
    operator: FilterOperator = FilterOperator.IS
    value: str | int | float | bool


class FilterGroup(StrictBaseModel):
    """Boolean group of conditions and nested filter groups."""

    mode: Literal["all", "any"] = "all"
    conditions: list[FilterCondition] = Field(default_factory=list[FilterCondition])
    groups: list[FilterGroup] = Field(default_factory=list["FilterGroup"])

    def is_empty(self) -> bool:
        """Return whether this group and all nested groups have no conditions."""
        return not self.conditions and all(group.is_empty() for group in self.groups)


class TmdbCollectionBuilder(StrictBaseModel):
    """Resolve movies belonging to one TMDB franchise collection."""

    type: Literal[BuilderType.TMDB_COLLECTION] = BuilderType.TMDB_COLLECTION
    collection_id: Annotated[int, Field(gt=0)]


class TmdbItemBuilder(StrictBaseModel):
    """Resolve explicit TMDB movie or show IDs in order."""

    type: Literal[BuilderType.TMDB_ITEM] = BuilderType.TMDB_ITEM
    tmdb_ids: Annotated[
        list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=1000)
    ]


class TmdbPersonBuilder(StrictBaseModel):
    """Resolve movies or shows credited to a TMDB person in selected roles."""

    type: Literal[BuilderType.TMDB_PERSON] = BuilderType.TMDB_PERSON
    person_id: Annotated[int, Field(gt=0)]
    person_name: Annotated[str, Field(max_length=200)] | None = None
    roles: Annotated[list[TmdbPersonRole], Field(min_length=1)] = Field(
        default_factory=lambda: [TmdbPersonRole.ACTOR]
    )
    use_biography: bool = False


class MdblistBuilder(StrictBaseModel):
    """Resolve one or more MDBList lists in source order."""

    type: Literal[BuilderType.MDBLIST] = BuilderType.MDBLIST
    identifiers: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(min_length=1, max_length=50),
    ]

    @field_validator("identifiers")
    @classmethod
    def validate_identifiers(cls, values: list[str]) -> list[str]:
        """Normalize every MDBList identifier or HTTPS list URL."""
        return [mdblist_identifier(value) for value in values]


class RadarrTagBuilder(StrictBaseModel):
    """Resolve movies carrying one or more Radarr tags."""

    type: Literal[BuilderType.RADARR_TAG] = BuilderType.RADARR_TAG
    tags: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=100),
    ]


class SonarrTagBuilder(StrictBaseModel):
    """Resolve shows carrying one or more Sonarr tags."""

    type: Literal[BuilderType.SONARR_TAG] = BuilderType.SONARR_TAG
    tags: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=100),
    ]


class LibraryFilterBuilder(StrictBaseModel):
    """Resolve library items matching a structured filter tree."""

    type: Literal[BuilderType.LIBRARY_FILTER] = BuilderType.LIBRARY_FILTER
    filter_group: FilterGroup

    @model_validator(mode="after")
    def validate_non_empty(self) -> Self:
        """Require at least one filter condition."""
        if self.filter_group.is_empty():
            raise ValueError("Choose at least one library filter condition")
        return self


type CollectionBuilder = Annotated[
    TmdbCollectionBuilder
    | TmdbItemBuilder
    | TmdbPersonBuilder
    | MdblistBuilder
    | RadarrTagBuilder
    | SonarrTagBuilder
    | LibraryFilterBuilder,
    Field(discriminator="type"),
]

builders_adapter: TypeAdapter[list[CollectionBuilder]] = TypeAdapter(
    list[CollectionBuilder]
)


class SmartCollectionConfig(StrictBaseModel):
    """Server-side smart collection filter, sort order and item limit."""

    filter_group: FilterGroup = Field(default_factory=FilterGroup)
    sort_by: SmartSortOrder = SmartSortOrder.RELEASE_DESC
    limit: Annotated[int, Field(ge=1, le=10000)] | None = None


class DynamicTmdbGroupConfig(StrictBaseModel):
    """Automatic TMDB franchise collection discovery for a collection group."""

    enabled: bool = False
    library_id: Annotated[str, Field(min_length=1, max_length=200)]
    strip_prefix: Annotated[str, Field(max_length=100)] = "The "
    strip_suffix: Annotated[str, Field(max_length=100)] = " Collection"
    exclude_tmdb_ids: list[Annotated[int, Field(gt=0)]] = Field(
        default_factory=list[int]
    )
    auto_exclude_from_other_collections: bool = True


class CollectionArtwork(StrictBaseModel):
    """Selected collection artwork and its completion state."""

    poster_url: str | None = None
    background_url: str | None = None
    poster_status: AssetStatus = AssetStatus.MISSING
    background_status: AssetStatus = AssetStatus.MISSING
    art_status: AssetStatus = AssetStatus.MISSING


def collection_artwork(row: MediaCollection) -> CollectionArtwork:
    """Project the collection's art slots without exposing server URLs."""
    completion = collection_art_completion(row)
    return CollectionArtwork(
        poster_url=read_art_slot(row, ArtType.POSTER).url,
        background_url=read_art_slot(row, ArtType.BACKGROUND).url,
        poster_status=completion.poster_status,
        background_status=completion.background_status,
        art_status=completion.art_status,
    )


class CollectionRead(CollectionArtwork):
    """Media-server collection response."""

    id: int
    kind: CollectionKind = CollectionKind.REGULAR
    title: str
    summary: str | None = None
    sort_title: str | None = None
    sort_title_format: str | None = None
    summary_format: str | None = None
    collection_group: str | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder = CollectionOrder.RELEASE
    collection_filtering: CollectionFiltering | None = None
    visible_home: bool = False
    visible_shared: bool = False
    visible_library: bool = False
    active_start_mmdd: str | None = None
    active_end_mmdd: str | None = None
    delete_when_inactive: bool | None = None
    withheld: bool = False
    thumb_url: str | None = None
    art_url: str | None = None
    child_count: int = 0
    below_minimum: bool = False
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
    auto_generated_tmdb_id: int | None = None
    #: The catalog has an OvertureDB theme for the collection's TMDB collection.
    public_dataset_complete: bool = False
    #: The catalog has a ThemerrDB theme for it.
    public_dataset_themerrdb: bool = False


class CollectionDetail(CollectionRead):
    """One collection with its members and what limits its theme."""

    effective_sync_mode: SyncMode = SyncMode.SYNC
    theme_duration: int | None = None
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
        **collection_artwork(row).model_dump(),
        id=row.id or 0,
        kind=row.kind,
        title=row.title,
        summary=row.summary,
        sort_title=row.sort_title,
        sort_title_format=row.sort_title_format,
        summary_format=row.summary_format,
        collection_group=row.collection_group,
        collection_mode=row.collection_mode,
        order_type=row.order_type,
        collection_filtering=row.collection_filtering,
        visible_home=row.visible_home,
        visible_shared=row.visible_shared,
        visible_library=row.visible_library,
        active_start_mmdd=row.active_start_mmdd,
        active_end_mmdd=row.active_end_mmdd,
        delete_when_inactive=row.delete_when_inactive,
        withheld=row.server_item_id is None,
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
        auto_generated_tmdb_id=row.auto_generated_tmdb_id,
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

    kind: CollectionKind = CollectionKind.REGULAR
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=10000)] | None = None
    summary_format: SummaryFormat | None = None
    sort_title: Annotated[str, Field(max_length=200)] | None = None
    sort_title_format: SortTitleFormat | None = None
    collection_group: Annotated[str, Field(max_length=200)] | None = None
    tmdb_collection_id: Annotated[int, Field(gt=0)] | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder = CollectionOrder.RELEASE
    collection_filtering: CollectionFiltering | None = None
    visible_home: bool = False
    visible_shared: bool = False
    visible_library: bool = False
    active_start_mmdd: SeasonalDate | None = None
    active_end_mmdd: SeasonalDate | None = None
    delete_when_inactive: bool | None = None

    @field_validator("collection_group")
    @classmethod
    def normalise_group(cls, value: str | None) -> str | None:
        """Keep unassigned groups null and custom names free of outer spaces."""
        return value.strip() or None if value is not None else None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        """Reject titles that become empty on the media server."""
        if not value.strip():
            raise ValueError("A collection needs a title")
        return value.strip()

    @model_validator(mode="after")
    def validate_seasonal_window(self) -> Self:
        """Require both start and end dates when a seasonal window is set."""
        if bool(self.active_start_mmdd) != bool(self.active_end_mmdd):
            raise ValueError(
                "Set both active_start_mmdd and active_end_mmdd "
                "for seasonal collections"
            )
        return self


class CollectionCreate(CollectionOptions):
    """Create a collection in one selected library."""

    media_type: MediaType
    library_id: Annotated[str, Field(min_length=1, max_length=200)]
    member_ids: Annotated[
        list[Annotated[int, Field(gt=0)]], Field(max_length=10000)
    ] = Field(default_factory=list[int])
    rule: CollectionRuleWrite | None = None


class CollectionMembersUpdate(StrictBaseModel):
    """Replace membership and optionally set its display order."""

    member_ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=10000)]
    order_type: CollectionOrder


class CollectionFilter(StrictBaseModel):
    """An intersection of filters over the current server library."""

    decade: Annotated[int, Field(ge=1800, le=3000, multiple_of=10)] | None = None
    studio: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    genre: Annotated[str, Field(min_length=1, max_length=200)] | None = None


def filter_group_from_legacy(filters: CollectionFilter) -> FilterGroup:
    """Convert a legacy CollectionFilter into a structured FilterGroup."""
    conditions: list[FilterCondition] = []
    if filters.decade is not None:
        conditions.append(
            FilterCondition(
                field=FilterField.DECADE,
                operator=FilterOperator.IS,
                value=filters.decade,
            )
        )
    if filters.studio is not None:
        conditions.append(
            FilterCondition(
                field=FilterField.STUDIO,
                operator=FilterOperator.IS,
                value=filters.studio,
            )
        )
    if filters.genre is not None:
        conditions.append(
            FilterCondition(
                field=FilterField.GENRE,
                operator=FilterOperator.IS,
                value=filters.genre,
            )
        )
    return FilterGroup(mode="all", conditions=conditions)


def legacy_filter_from_group(group: FilterGroup) -> CollectionFilter:
    """Project simple decade/studio/genre conditions back to CollectionFilter."""
    decade: int | None = None
    studio: str | None = None
    genre: str | None = None
    for condition in group.conditions:
        if condition.operator is not FilterOperator.IS:
            continue
        if condition.field is FilterField.DECADE and isinstance(condition.value, int):
            decade = condition.value
        elif condition.field is FilterField.STUDIO and isinstance(condition.value, str):
            studio = condition.value
        elif condition.field is FilterField.GENRE and isinstance(condition.value, str):
            genre = condition.value
    return CollectionFilter(decade=decade, studio=studio, genre=genre)


def builders_from_legacy(
    source_type: RuleSourceType,
    source_identifier: str,
    filters: CollectionFilter,
) -> list[CollectionBuilder]:
    """Convert legacy single-source rule fields into a builder list."""
    if source_type is RuleSourceType.TMDB:
        return [TmdbCollectionBuilder(collection_id=int(source_identifier))]
    if source_type is RuleSourceType.MDBLIST:
        return [MdblistBuilder(identifiers=[source_identifier])]
    return [LibraryFilterBuilder(filter_group=filter_group_from_legacy(filters))]


class CollectionRuleWrite(StrictBaseModel):
    """Composable dynamic builders or smart filter with nullable policy overrides."""

    source_type: RuleSourceType = RuleSourceType.FILTER
    source_identifier: Annotated[str, Field(max_length=500)] = ""
    filters: CollectionFilter = Field(default_factory=CollectionFilter)
    builders: list[CollectionBuilder] = Field(default_factory=list[CollectionBuilder])
    smart_filter: SmartCollectionConfig | None = None
    managed_label: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    sync_mode: SyncMode | None = None
    minimum_items: Annotated[int, Field(ge=1, le=100)] | None = None
    delete_below_minimum: bool | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder | None = None
    collection_filtering: CollectionFiltering | None = None
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    sort_title_format: SortTitleFormat | None = None
    summary_format: SummaryFormat | None = None
    active_start_mmdd: SeasonalDate | None = None
    active_end_mmdd: SeasonalDate | None = None
    delete_when_inactive: bool | None = None
    auto_match_art: bool | None = None
    auto_match_theme: bool | None = None
    sync_interval_hours: Annotated[int, Field(ge=1, le=8760)] = 24
    enabled: bool = True

    @field_validator("managed_label")
    @classmethod
    def strip_managed_label(cls, value: str | None) -> str | None:
        """Keep managed Plex labels trimmed."""
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """Accept structured builders, smart filters, or legacy single-source rules."""
        if bool(self.active_start_mmdd) != bool(self.active_end_mmdd):
            raise ValueError(
                "Set both active_start_mmdd and active_end_mmdd "
                "for seasonal collections"
            )
        if self.builders:
            first = self.builders[0]
            if isinstance(first, TmdbCollectionBuilder):
                self.source_type = RuleSourceType.TMDB
                self.source_identifier = str(first.collection_id)
            elif isinstance(first, MdblistBuilder):
                self.source_type = RuleSourceType.MDBLIST
                self.source_identifier = first.identifiers[0]
            elif isinstance(first, LibraryFilterBuilder):
                self.source_type = RuleSourceType.FILTER
                self.source_identifier = ""
                self.filters = legacy_filter_from_group(first.filter_group)
            else:
                self.source_type = RuleSourceType.FILTER
                self.source_identifier = ""
            return self
        if self.smart_filter is not None:
            if self.smart_filter.filter_group.is_empty() and not self.managed_label:
                raise ValueError(
                    "Smart collections require at least one filter condition "
                    "or managed label"
                )
            return self
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
        self.builders = builders_from_legacy(
            self.source_type, self.source_identifier, self.filters
        )
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


class CollectionGroupPolicy(StrictBaseModel):
    """Nullable group defaults; null inherits the application setting."""

    sync_mode: SyncMode | None = None
    minimum_items: Annotated[int, Field(ge=1, le=100)] | None = None
    delete_below_minimum: bool | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder | None = None
    collection_filtering: CollectionFiltering | None = None
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    sort_title_format: SortTitleFormat | None = None
    summary_format: SummaryFormat | None = None
    active_start_mmdd: SeasonalDate | None = None
    active_end_mmdd: SeasonalDate | None = None
    delete_when_inactive: bool | None = None
    auto_match_art: bool | None = None
    auto_match_theme: bool | None = None
    sync_interval_hours: Annotated[int, Field(ge=1, le=8760)] | None = None
    sync_enabled: bool | None = None
    dynamic_tmdb: DynamicTmdbGroupConfig | None = None

    @model_validator(mode="after")
    def validate_seasonal_window(self) -> Self:
        """Require both start and end dates when a seasonal window is set."""
        if bool(self.active_start_mmdd) != bool(self.active_end_mmdd):
            raise ValueError(
                "Set both active_start_mmdd and active_end_mmdd for seasonal groups"
            )
        return self


class CollectionGenerateRequest(CollectionGroupPolicy):
    """Preview or generate collections from metadata already in the library."""

    media_type: MediaType
    library_id: Annotated[str, Field(min_length=1)]
    preset: CollectionPreset
    collection_group: Annotated[str, Field(max_length=200)] | None = None
    titles: Annotated[list[str], Field(max_length=100)] = Field(default_factory=list)


class CollectionPresetRead(StrictBaseModel):
    """A generator candidate with its matching library count."""

    title: str
    count: int
    filters: CollectionFilter
    tmdb_collection_id: int | None = None


class CollectionGenerateResponse(StrictBaseModel):
    """Per-collection generator results; one failure leaves others intact."""

    created: list[int] = Field(default_factory=list[int])
    errors: dict[str, str] = Field(default_factory=dict)


class BulkCollectionOperation(StrictBaseModel):
    """One bounded operation over an explicit collection selection."""

    collection_ids: Annotated[
        list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=1000)
    ]
    media_type: MediaType
    operation: Literal[
        "set_visibility",
        "set_order",
        "set_monitored",
        "set_group",
        "apply_sort_title_format",
        "trigger_sync",
        "delete",
    ]
    collection_mode: CollectionMode | None = None
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    order_type: CollectionOrder | None = None
    monitored: bool | None = None
    collection_group: Annotated[str, Field(max_length=200)] | None = None
    sort_title_format: SortTitleFormat | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        """Reject missing operation arguments before any server writes."""
        if len(set(self.collection_ids)) != len(self.collection_ids):
            raise ValueError("Select distinct collections")
        required = {
            "set_order": self.order_type,
            "set_monitored": self.monitored,
            "apply_sort_title_format": self.sort_title_format,
        }
        if self.operation in required and required[self.operation] is None:
            raise ValueError("The operation requires a value")
        if self.operation == "set_visibility" and not {
            "collection_mode",
            "visible_home",
            "visible_shared",
            "visible_library",
        }.intersection(self.model_fields_set):
            raise ValueError("Choose visibility or home promotion")
        return self


class BulkCollectionOperationResult(StrictBaseModel):
    """Successful identities and sanitised errors, committed independently."""

    collection_ids: list[int] = Field(default_factory=list[int])
    errors: dict[int, str] = Field(default_factory=dict[int, str])
