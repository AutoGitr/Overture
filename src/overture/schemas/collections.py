"""Collection REST and WebSocket schemas."""

lazy import hashlib
lazy from datetime import date, datetime
lazy from typing import Annotated, Literal, Self

lazy from pydantic import Field, TypeAdapter, field_validator, model_validator

lazy from ..config import API_PREFIX
lazy from ..db.art_slots import read_art_slot
lazy from ..db.completion import collection_art_completion, collection_theme_status
lazy from ..db.models.collection_rule import CollectionRule
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.public_dataset import PublicDatasetCollection
lazy from ..domain import (
    SMART_CUSTOM_ORDER,
    ArtSource,
    ArtType,
    AssetStatus,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    FieldKind,
    FilterField,
    FilterOperator,
    MediaType,
    ServerType,
    SetDimension,
    SourceType,
    SyncMode,
    TmdbChart,
    TmdbPersonRole,
)
lazy from ..integrations.mdblist import mdblist_identifier
lazy from ..services.collections.fields import FIELDS, OPERATORS
lazy from ..utils.art_urls import selected_art_source
lazy from ..utils.collection_formats import (
    MAX_COLLECTION_SUMMARY_LENGTH,
    MemberTagFormat,
    SeasonalDate,
    SetTitleFormat,
    SortTitleFormat,
    SummaryFormat,
)
lazy from .base import StrictBaseModel
lazy from .common import StatusResponse
lazy from .library import MediaItemRead
lazy from .validators import CronExpression, GroupName, YouTubeId


class ArrTagRead(StrictBaseModel):
    """One tag configured on Radarr or Sonarr."""

    id: int
    label: str


class FieldCondition(StrictBaseModel):
    """Test one metadata field of an item."""

    kind: Literal["field"] = "field"
    field: FilterField
    operator: FilterOperator = FilterOperator.IS
    #: Days for ``in_last`` and ``not_in_last``; an ISO date for ``before`` and
    #: ``after``.
    value: str | int | float | bool

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        """Accept only the field's operators and normalise the value to its kind."""
        kind = FIELDS[self.field].kind
        if self.operator not in OPERATORS[kind]:
            raise ValueError(
                f"{FIELDS[self.field].label} cannot use the {self.operator} operator"
            )
        self.value = _condition_value(kind, self.operator, self.value)
        return self


def _condition_value(
    kind: FieldKind, operator: FilterOperator, value: str | int | float | bool
) -> str | int | float | bool:
    if kind is FieldKind.BOOLEAN:
        if isinstance(value, bool):
            return value
        raise ValueError("Choose true or false")
    if kind is FieldKind.NUMBER or operator in {
        FilterOperator.IN_LAST,
        FilterOperator.NOT_IN_LAST,
    }:
        if isinstance(value, bool):
            raise ValueError("Enter a number")
        try:
            number = float(value)
        except ValueError:
            raise ValueError("Enter a number") from None
        if kind is FieldKind.DATE:
            if number < 1 or not number.is_integer():
                raise ValueError("Enter a whole number of days")
            return int(number)
        return int(number) if number.is_integer() else number
    text = str(value).strip()
    if kind is FieldKind.DATE:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise ValueError("Enter a date as YYYY-MM-DD") from None
    if not text:
        raise ValueError("Enter a value")
    return text


class TmdbCollectionSource(StrictBaseModel):
    """Movies in one TMDB franchise collection, in release order."""

    type: Literal[SourceType.TMDB_COLLECTION] = SourceType.TMDB_COLLECTION
    collection_id: Annotated[int, Field(gt=0)]


class TmdbItemSource(StrictBaseModel):
    """Explicit TMDB movie or show IDs, in the order given."""

    type: Literal[SourceType.TMDB_ITEM] = SourceType.TMDB_ITEM
    tmdb_ids: Annotated[
        list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=1000)
    ]


class TmdbListSource(StrictBaseModel):
    """Public TMDB lists, in their saved order."""

    type: Literal[SourceType.TMDB_LIST] = SourceType.TMDB_LIST
    list_ids: Annotated[
        list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=50)
    ]


class TmdbPersonSource(StrictBaseModel):
    """Movies or shows credited to a TMDB person in selected roles."""

    type: Literal[SourceType.TMDB_PERSON] = SourceType.TMDB_PERSON
    person_id: Annotated[int, Field(gt=0)]
    person_name: Annotated[str, Field(max_length=200)] | None = None
    roles: Annotated[list[TmdbPersonRole], Field(min_length=1)] = Field(
        default_factory=lambda: [TmdbPersonRole.ACTOR]
    )


class TmdbChartSource(StrictBaseModel):
    """The top titles of a TMDB chart, such as Popular or Trending this week."""

    type: Literal[SourceType.TMDB_CHART] = SourceType.TMDB_CHART
    chart: TmdbChart
    limit: Annotated[int, Field(ge=1, le=500)] = 100


class MdblistSource(StrictBaseModel):
    """One or more MDBList lists, in source order."""

    type: Literal[SourceType.MDBLIST] = SourceType.MDBLIST
    identifiers: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(min_length=1, max_length=50),
    ]

    @field_validator("identifiers")
    @classmethod
    def validate_identifiers(cls, values: list[str]) -> list[str]:
        """Normalize every MDBList identifier or HTTPS list URL."""
        return [mdblist_identifier(value) for value in values]


class RadarrTagSource(StrictBaseModel):
    """Movies carrying any of the Radarr tags."""

    type: Literal[SourceType.RADARR_TAG] = SourceType.RADARR_TAG
    tags: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=100),
    ]


class SonarrTagSource(StrictBaseModel):
    """Shows carrying any of the Sonarr tags."""

    type: Literal[SourceType.SONARR_TAG] = SourceType.SONARR_TAG
    tags: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=100),
    ]


type CollectionSource = Annotated[
    TmdbCollectionSource
    | TmdbItemSource
    | TmdbListSource
    | TmdbPersonSource
    | TmdbChartSource
    | MdblistSource
    | RadarrTagSource
    | SonarrTagSource,
    Field(discriminator="type"),
]


class SourceCondition(StrictBaseModel):
    """Test whether an external list holds the item."""

    kind: Literal["source"] = "source"
    operator: Literal[FilterOperator.IS, FilterOperator.IS_NOT] = FilterOperator.IS
    source: CollectionSource

    @property
    def key(self) -> str:
        """Identify the source, so identical sources resolve once."""
        return _source_key.dump_json(self.source).decode()


_source_key: TypeAdapter[CollectionSource] = TypeAdapter(CollectionSource)

type Condition = Annotated[
    FieldCondition | SourceCondition, Field(discriminator="kind")
]


class FilterGroup(StrictBaseModel):
    """Conditions and nested groups, matched together or individually."""

    mode: Literal["all", "any"] = "all"
    conditions: Annotated[list[Condition], Field(max_length=100)] = Field(
        default_factory=list[Condition]
    )
    groups: Annotated[list[FilterGroup], Field(max_length=20)] = Field(
        default_factory=list["FilterGroup"]
    )

    def is_empty(self) -> bool:
        """Return whether this group and all nested groups have no conditions."""
        return not self.conditions and all(group.is_empty() for group in self.groups)

    def source_conditions(self) -> list[SourceCondition]:
        """Every source condition, depth first, in the order sources rank items."""
        return [
            *(
                condition
                for condition in self.conditions
                if isinstance(condition, SourceCondition)
            ),
            *(
                condition
                for group in self.groups
                for condition in group.source_conditions()
            ),
        ]

    def field_conditions(self) -> list[FieldCondition]:
        """Every field condition in the tree."""
        return [
            *(
                condition
                for condition in self.conditions
                if isinstance(condition, FieldCondition)
            ),
            *(
                condition
                for group in self.groups
                for condition in group.field_conditions()
            ),
        ]


class CollectionArtwork(StrictBaseModel):
    """Selected collection artwork and its completion state."""

    poster_url: str | None = None
    background_url: str | None = None
    poster_source: ArtSource | None = None
    background_source: ArtSource | None = None
    poster_width: int | None = None
    poster_height: int | None = None
    background_width: int | None = None
    background_height: int | None = None
    poster_status: AssetStatus = AssetStatus.MISSING
    background_status: AssetStatus = AssetStatus.MISSING
    art_status: AssetStatus = AssetStatus.MISSING


def collection_artwork(row: MediaCollection) -> CollectionArtwork:
    """Project the collection's art slots without exposing server URLs."""
    completion = collection_art_completion(row)
    poster = read_art_slot(row, ArtType.POSTER)
    background = read_art_slot(row, ArtType.BACKGROUND)
    return CollectionArtwork(
        poster_url=poster.url,
        background_url=background.url,
        poster_source=selected_art_source(poster.url),
        background_source=selected_art_source(background.url),
        poster_width=poster.width,
        poster_height=poster.height,
        background_width=background.width,
        background_height=background.height,
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
    order_type: CollectionOrder = CollectionOrder.RELEASE_ASC
    collection_filtering: CollectionFiltering | None = None
    visible_home: bool = False
    visible_shared: bool = False
    visible_library: bool = False
    active_start_mmdd: str | None = None
    active_end_mmdd: str | None = None
    delete_when_inactive: bool | None = None
    withheld: bool = False
    #: Overture holds saved changes the media server does not have yet.
    unsynced: bool = False
    #: Overture maintains the members from criteria.
    managed: bool = False
    #: The last sync of the criteria failed.
    sync_failed: bool = False
    last_rule_sync: datetime | None = None
    #: The collection set value the collection was created for.
    generated_value: str | None = None
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
    theme_duration: int | None = None
    theme_status: AssetStatus = AssetStatus.MISSING
    monitored: bool = True
    tmdb_collection_id: int | None = None
    #: The catalog has an OvertureDB theme for the collection's TMDB collection.
    public_dataset_complete: bool = False
    #: The catalog has a ThemerrDB theme for it.
    public_dataset_themerrdb: bool = False
    #: The poster or background is outside the aspect ratio tolerance.
    has_incorrect_aspect_ratio: bool = False
    #: OvertureDB says the collection has no theme music, so none is missing.
    catalog_no_theme: bool = False
    #: Where Plex's Home lists it among promoted collections, lowest first.
    home_order: int | None = None


class CollectionDetail(CollectionRead):
    """One collection with its members and what limits its theme."""

    effective_sync_mode: SyncMode = SyncMode.SYNC
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
    row: MediaCollection,
    catalog: PublicDatasetCollection | None,
    rule: CollectionRule | None = None,
    *,
    trust_no_theme: bool = True,
) -> CollectionRead:
    """Map a stored collection, its catalog entry and its rule to public output.

    *trust_no_theme* lets the catalog's No theme flag count as a theme.
    """
    has_theme = row.server_theme_id is not None or row.theme_file_hash is not None
    no_theme = trust_no_theme and catalog is not None and catalog.no_theme
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
        unsynced=row.unsynced,
        managed=rule is not None,
        sync_failed=bool(rule and rule.last_error),
        last_rule_sync=rule.last_synced_at if rule else None,
        generated_value=row.generated_value,
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
        theme_duration=row.theme_file_duration or row.youtube_duration,
        theme_status=AssetStatus.COMPLETE
        if no_theme
        else collection_theme_status(
            server_has_theme=has_theme, youtube_id=row.youtube_id
        ),
        catalog_no_theme=no_theme,
        monitored=row.monitored,
        tmdb_collection_id=row.tmdb_collection_id,
        public_dataset_complete=bool(
            catalog and (catalog.youtube_id_overturedb or no_theme)
        ),
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


class CollectionPolicyBase(StrictBaseModel):
    """Shared policy and media server display configuration."""

    sync_mode: SyncMode | None = None
    minimum_items: Annotated[int, Field(ge=1, le=100)] | None = None
    delete_below_minimum: bool | None = None
    auto_match_art: bool | None = None
    auto_match_theme: bool | None = None
    delete_when_inactive: bool | None = None
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
    #: Ask Radarr or Sonarr for list titles the library lacks after each sync.
    request_missing: bool | None = None
    #: A server label members get and other items lose; {title} and {group}.
    member_label: MemberTagFormat | None = None
    #: A Radarr or Sonarr tag members get and other titles lose.
    arr_tag: MemberTagFormat | None = None
    #: Where a promoted collection's row sits on Plex's Home; lower comes first.
    home_order: Annotated[int, Field(ge=1, le=999)] | None = None

    @model_validator(mode="after")
    def validate_seasonal_window(self) -> Self:
        """Require both start and end dates when a seasonal window is set."""
        if bool(self.active_start_mmdd) != bool(self.active_end_mmdd):
            raise ValueError(
                "Set both active_start_mmdd and active_end_mmdd "
                "for seasonal collections"
            )
        return self


class CollectionOptions(StrictBaseModel):
    """Editable collection metadata and server display options."""

    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=MAX_COLLECTION_SUMMARY_LENGTH)] | None = (
        None
    )
    summary_format: SummaryFormat | None = None
    sort_title: Annotated[str, Field(max_length=200)] | None = None
    sort_title_format: SortTitleFormat | None = None
    collection_group: GroupName | None = None
    tmdb_collection_id: Annotated[int, Field(gt=0)] | None = None
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder = CollectionOrder.RELEASE_ASC
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
    """Create a collection in one selected library; its criteria decide its members."""

    media_type: MediaType
    library_id: Annotated[str, Field(min_length=1, max_length=200)]
    rule: CollectionRuleWrite


class CollectionMembersUpdate(StrictBaseModel):
    """Replace membership and optionally set its display order."""

    member_ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=10000)]
    order_type: CollectionOrder


class CollectionRuleWrite(CollectionPolicyBase):
    """Criteria that decide membership, with nullable policy overrides."""

    criteria: FilterGroup
    #: Plex evaluates the criteria live instead of Overture on each sync.
    smart: bool = False
    limit: Annotated[int, Field(ge=1, le=10000)] | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        """Require a condition, and leave smart collections to Plex's order."""
        if self.criteria.is_empty():
            raise ValueError("Add at least one condition")
        if self.smart and self.order_type is CollectionOrder.CUSTOM:
            raise ValueError(SMART_CUSTOM_ORDER)
        return self


class CollectionRuleRead(CollectionRuleWrite):
    """Saved rule with its most recent outcome."""

    last_synced_at: datetime | None = None
    last_error: str | None = None
    #: The description of the first list, which {source_summary} shows.
    source_summary: str | None = None


class CollectionSyncResponse(StrictBaseModel):
    """What one rule run changed."""

    added: int = 0
    removed: int = 0
    skipped: bool = False
    deleted: bool = False


class CustomSetValue(StrictBaseModel):
    """One collection of a custom set."""

    name: Annotated[str, Field(min_length=1, max_length=200)]
    criteria: FilterGroup

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        """Each collection needs a condition of its own."""
        if self.criteria.is_empty():
            raise ValueError(f"Add a condition to {self.name}")
        return self


class SetValueAlias(StrictBaseModel):
    """Values that make one collection under a name of their own."""

    values: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=50),
    ]
    name: Annotated[str, Field(min_length=1, max_length=200)]


class CollectionGeneratorBase(StrictBaseModel):
    """What a collection set creates one collection for, before a library is chosen."""

    dimension: SetDimension
    include: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(max_length=500),
    ] = Field(default_factory=list[str])
    exclude: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(max_length=500),
    ] = Field(default_factory=list[str])
    #: Only the values with the most items.
    top: Annotated[int, Field(ge=1, le=500)] | None = None
    title_format: SetTitleFormat = "{value}"
    strip_prefix: Annotated[str, Field(max_length=100)] = ""
    strip_suffix: Annotated[str, Field(max_length=100)] = ""
    #: Conditions every collection in the set adds to its value's condition.
    criteria: FilterGroup = Field(default_factory=FilterGroup)
    smart: bool = False
    #: The collections of a custom set, each with its own conditions.
    custom_values: Annotated[list[CustomSetValue], Field(max_length=200)] = Field(
        default_factory=list[CustomSetValue]
    )
    #: Values renamed, or merged into one collection.
    aliases: Annotated[list[SetValueAlias], Field(max_length=200)] = Field(
        default_factory=list[SetValueAlias]
    )

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """A custom set lists its collections; other sets find them."""
        if (self.dimension is SetDimension.CUSTOM) != bool(self.custom_values):
            raise ValueError(
                "Add the custom set's collections"
                if self.dimension is SetDimension.CUSTOM
                else "Only custom sets list their collections"
            )
        names = [value.name.casefold() for value in self.custom_values]
        if len(names) != len(set(names)):
            raise ValueError("Give each collection of the set its own name")
        return self


class CollectionGenerator(CollectionGeneratorBase):
    """A collection set: its collections in each of its libraries."""

    library_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=20),
    ]


class CollectionGroupPolicy(CollectionPolicyBase):
    """Nullable group defaults; null inherits the application setting.

    Only groups and the application schedule syncs; a collection follows its group.
    """

    #: When scheduled syncs run, as a cron expression.
    sync_schedule: CronExpression | None = None
    sync_enabled: bool | None = None

    generator: CollectionGenerator | None = None


class CollectionTakeOver(StrictBaseModel):
    """The group a collection joins when Overture takes it over."""

    group: GroupName | None = None


class CollectionGroupRename(StrictBaseModel):
    """A replacement group name, scoped by the request."""

    name: Annotated[GroupName, Field(min_length=1)]


type CollectionDeleteTarget = Literal["server", "both"]


class CollectionGroupDelete(StrictBaseModel):
    """What happens to a deleted group's collections.

    ``keep`` moves them to Ungrouped, ``move`` puts them in *group*,
    ``overture`` forgets them (the server copies return as Unmanaged on the
    next import) and ``both`` deletes them from the server too.
    """

    collections: Literal["keep", "move", "overture", "both"] = "keep"
    group: GroupName | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Moving needs a group to move to, and only moving takes one."""
        if (self.collections == "move") != bool(self.group and self.group.strip()):
            raise ValueError("Name the group to move the collections to")
        return self


class CollectionSetPreview(StrictBaseModel):
    """Preview a set's collections in its library before saving it."""

    media_type: MediaType
    generator: CollectionGenerator
    #: The group the set saves into, whose existing collections are matched.
    group: Annotated[str, Field(max_length=200)] | None = None
    minimum_items: Annotated[int, Field(ge=1, le=100)] | None = None


class CollectionSetEntry(StrictBaseModel):
    """One collection a set creates, keeps or skips, in one of its libraries."""

    library_id: str
    value: str
    title: str
    member_count: int
    below_minimum: bool
    #: The set's existing collection for the value.
    collection_id: int | None = None


class CollectionMissingTitle(StrictBaseModel):
    """A title a collection's lists hold that the library lacks."""

    tmdb_id: int
    title: str
    year: int | None = None
    poster_url: str | None = None
    #: Radarr or Sonarr already has it.
    requested: bool = False


class CollectionMissing(StrictBaseModel):
    """What a collection's lists hold beyond the library."""

    titles: list[CollectionMissingTitle]
    #: More titles are missing than are listed.
    truncated: bool = False
    #: Radarr or Sonarr is set up to take requests for the library.
    requestable: bool = False


class CollectionRequest(StrictBaseModel):
    """Titles to request; none requests every missing one."""

    tmdb_ids: (
        Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=500)] | None
    ) = None


class CollectionRequestResult(StrictBaseModel):
    """What a request added to Radarr or Sonarr."""

    requested: int = 0
    #: Already in Radarr or Sonarr.
    present: int = 0
    errors: list[str] = Field(default_factory=list[str])


class CollectionArrOptions(StrictBaseModel):
    """Where Radarr or Sonarr can put requested titles."""

    root_folders: list[str]
    quality_profiles: list[ArrTagRead]


class KindRecommendation(StrictBaseModel):
    """The collection kind that suits the criteria, and why."""

    kind: CollectionKind
    reason: str


class CollectionPreview(StrictBaseModel):
    """What a collection's criteria select now, before it is saved."""

    member_count: int
    #: The first members, in the collection's order.
    members: list[str]
    #: Only on servers with smart collections.
    recommendation: KindRecommendation | None = None


class CollectionPreviewRequest(StrictBaseModel):
    """Criteria to preview in one library."""

    media_type: MediaType
    library_id: Annotated[str, Field(min_length=1, max_length=200)]
    rule: CollectionRuleWrite


class CollectionGroupSyncResult(StrictBaseModel):
    """What syncing a group created, removed and failed to sync."""

    created: list[int] = Field(default_factory=list[int])
    removed: list[int] = Field(default_factory=list[int])
    synced: int = 0
    errors: dict[str, str] = Field(default_factory=dict[str, str])


class CollectionPresetCollection(StrictBaseModel):
    """A single collection a preset starts from."""

    title: str
    collection_filtering: CollectionFiltering | None = None
    rule: CollectionRuleWrite


class CollectionPresetSet(StrictBaseModel):
    """A collection set a preset starts from."""

    group: str
    policy: CollectionPolicyBase
    generator: CollectionGeneratorBase


class CollectionPresetRead(StrictBaseModel):
    """A starting point for a new collection or collection set."""

    key: str
    label: str
    description: str
    collection: CollectionPresetCollection | None = None
    set: CollectionPresetSet | None = None
    #: Set for a preset saved from the form, which can be deleted.
    saved_id: int | None = None


class CollectionPresetSave(StrictBaseModel):
    """A collection or set to keep as a preset."""

    media_type: MediaType
    label: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=500)] = ""
    collection: CollectionPresetCollection | None = None
    set: CollectionPresetSet | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        """A preset makes either one collection or a set."""
        if (self.collection is None) == (self.set is None):
            raise ValueError("Save either a collection or a set")
        return self


class CollectionFieldRead(StrictBaseModel):
    """A criteria field as the active server offers it."""

    field: FilterField
    label: str
    kind: FieldKind
    operators: list[FilterOperator]
    #: Overture can evaluate it from synced metadata.
    local: bool
    #: Plex smart collections can test it.
    smart: bool


class CollectionSourceRead(StrictBaseModel):
    """A source condition type, and why it is unavailable if it is."""

    type: SourceType
    label: str
    unavailable: str | None = None


class CollectionDimensionRead(StrictBaseModel):
    """A metadata dimension a collection set can enumerate."""

    dimension: SetDimension
    label: str
    title_format: str
    #: Only a set of Plex smart collections can enumerate it.
    smart_only: bool = False


class CollectionCapabilities(StrictBaseModel):
    """What the active media server lets collections do, for one media type."""

    server_type: ServerType
    smart: bool
    #: Plex's visibility, Home promotion and Home order.
    visibility: bool
    #: The server takes labels Overture puts on members.
    member_labels: bool
    #: Radarr (movies) or Sonarr (shows) can take requests and tags.
    arr: bool
    orders: list[CollectionOrder]
    smart_orders: list[CollectionOrder]
    fields: list[CollectionFieldRead]
    sources: list[CollectionSourceRead]
    dimensions: list[CollectionDimensionRead]
    #: The TMDB charts there are for the media type.
    charts: list[TmdbChart]


class CollectionFieldValue(StrictBaseModel):
    """A value of a field in a library, with the number of items holding it."""

    value: str
    count: int


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
        "take_over",
        "clear_artwork",
        "clear_themes",
        "delete",
    ]
    collection_mode: CollectionMode | None = None
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    order_type: CollectionOrder | None = None
    monitored: bool | None = None
    collection_group: GroupName | None = None
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
    #: Collections left as they were, and why.
    skipped: dict[int, str] = Field(default_factory=dict[int, str])
