"""Collection REST and WebSocket schemas."""

lazy from collections.abc import Sequence
lazy from datetime import date, datetime
lazy from typing import Annotated, Literal, Self

lazy from pydantic import (
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

lazy from ..db.ledger import Destination, combined_status, delivery, read_asset
lazy from ..db.models.catalog import CatalogCollection
lazy from ..db.models.collection_rule import CollectionRule
lazy from ..db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ..domain import (
    SMART_CUSTOM_ORDER,
    ArtStyle,
    AssetStatus,
    AutoArtSource,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    CollectionPosterStyle,
    FieldKind,
    FilterField,
    FilterOperator,
    MediaType,
    MetadataIssue,
    ServerAsset,
    ServerType,
    SetDimension,
    SourceType,
    SyncMode,
    TmdbChart,
    TmdbPersonRole,
)
lazy from ..integrations.mdblist import mdblist_identifier
lazy from ..media_servers.adapters import image_version
lazy from ..utils.collection_fields import (
    FIELDS,
    OPERATORS,
    field_label,
    field_operators,
)
lazy from ..utils.collection_formats import (
    MAX_COLLECTION_SUMMARY_LENGTH,
    MemberTagFormat,
    SeasonalDate,
    SetTitleFormat,
    SortTitleFormat,
    SummaryFormat,
)
lazy from .assets import AssetRead, TitleAssets, assets_read
lazy from .base import PositiveId, PublicText, StrictBaseModel
lazy from .catalog import CatalogSelections
lazy from .common import StatusResponse
lazy from .removal import AssetRemoval
lazy from .validators import CollectionIds, GroupName, UniqueList, YouTubeId

type LibraryId = Annotated[str, Field(min_length=1, max_length=200)]


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
        if FIELDS[self.field].by_id and not (
            isinstance(self.value, str)
            and self.value.isascii()
            and self.value.isdecimal()
        ):
            raise ValueError(f"Choose a {FIELDS[self.field].label.lower()} by its ID")
        return self

    @property
    def key(self) -> str:
        """Identify the condition, so identical conditions share one label."""
        return self.model_dump_json()


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
    collection_id: PositiveId


#: TMDB IDs one TMDB titles source names.
TMDB_ITEM_IDS_MAX = 1000
#: Conditions one criteria group holds.
GROUP_CONDITIONS_MAX = 100
#: Groups one criteria group nests.
GROUP_GROUPS_MAX = 20


class TmdbItemSource(StrictBaseModel):
    """Explicit TMDB movie or show IDs, in the order given."""

    type: Literal[SourceType.TMDB_ITEM] = SourceType.TMDB_ITEM
    tmdb_ids: Annotated[
        list[PositiveId], Field(min_length=1, max_length=TMDB_ITEM_IDS_MAX)
    ]


class TmdbListSource(StrictBaseModel):
    """Public TMDB lists, in their saved order."""

    type: Literal[SourceType.TMDB_LIST] = SourceType.TMDB_LIST
    list_ids: Annotated[list[PositiveId], Field(min_length=1, max_length=50)]


class TmdbPersonSource(StrictBaseModel):
    """Movies or shows credited to a TMDB person in selected roles."""

    type: Literal[SourceType.TMDB_PERSON] = SourceType.TMDB_PERSON
    person_id: PositiveId
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


#: A source that is a list of titles, which a library may lack some of. A
#: plain union, so the API's schema of every source stays one flat list.
ListingSource = (
    TmdbCollectionSource
    | TmdbItemSource
    | TmdbListSource
    | TmdbPersonSource
    | TmdbChartSource
    | MdblistSource
)

type CollectionSource = Annotated[
    ListingSource | RadarrTagSource | SonarrTagSource,
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
    conditions: Annotated[list[Condition], Field(max_length=GROUP_CONDITIONS_MAX)] = (
        Field(default_factory=list[Condition])
    )
    groups: Annotated[list[FilterGroup], Field(max_length=GROUP_GROUPS_MAX)] = Field(
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

    def names_titles(self) -> bool:
        """Whether it names titles by TMDB ID, which differ between movies and shows."""
        return any(
            isinstance(condition.source, TmdbItemSource)
            for condition in self.source_conditions()
        )

    def listing_sources(self) -> list[ListingSource]:
        """The included lists, which can hold titles the library lacks.

        Radarr and Sonarr tags hold titles the library has or is downloading,
        and an excluded list adds none, so only included TMDB and MDBList lists
        count.
        """
        return [
            condition.source
            for condition in self.source_conditions()
            if condition.operator is FilterOperator.IS
            and not isinstance(condition.source, RadarrTagSource | SonarrTagSource)
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


class CollectionCopyRead(StrictBaseModel):
    """One media server's collection holding the collection's members."""

    #: The database's number of the server.
    server_id: int
    #: The server's own ID of the collection, which its web app opens.
    server_item_id: str
    #: The collection's libraries whose members this server collection holds.
    library_ids: list[str]


class CollectionRead(StrictBaseModel):
    """Media-server collection response."""

    id: int
    #: The poster, background and theme.
    assets: TitleAssets
    #: The poster and background taken together.
    art_status: AssetStatus = AssetStatus.MISSING
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
    #: The gaps in the collection's metadata.
    metadata_issues: list[MetadataIssue] = Field(default_factory=list[MetadataIssue])
    #: Overture holds saved changes the media server does not have yet.
    unsynced: bool = False
    #: Overture maintains the members from criteria.
    managed: bool = False
    #: The last sync of the criteria failed.
    sync_failed: bool = False
    last_rule_sync: datetime | None = None
    #: The collection set value the collection was created for.
    generated_value: str | None = None
    #: Name the lead copy's current poster and background, as ``t`` of their
    #: image route, so a replaced one is fetched anew; ``None`` without one.
    server_poster_version: str | None = None
    server_background_version: str | None = None
    child_count: int = 0
    below_minimum: bool = False
    #: What its libraries hold, movies first.
    media_types: list[MediaType]
    library_ids: list[str]
    server_added_at: str | None = None
    #: Its collections on the configured servers, the lead first: the one
    #: whose images and link stand for it. None while it is withheld.
    copies: list[CollectionCopyRead] = Field(default_factory=list[CollectionCopyRead])
    monitored: bool = True
    tmdb_collection_id: int | None = None
    #: The catalog has an OvertureDB theme for the collection's TMDB collection.
    catalog_complete: bool = False
    #: The catalog has a ThemerrDB theme for it.
    catalog_themerrdb: bool = False
    #: How each selection compares with the collection's OvertureDB entry;
    #: null without an entry.
    catalog_selections: CatalogSelections | None = None
    #: The poster or background is outside the aspect ratio tolerance.
    has_incorrect_aspect_ratio: bool = False
    #: What a poster chosen for it next is contributed to OvertureDB as.
    contributed_style: CollectionPosterStyle = CollectionPosterStyle.INDIVIDUAL
    #: Where Plex's Home lists it among promoted collections, lowest first.
    home_order: int | None = None


class CollectionDetail(CollectionRead):
    """One collection with its members and what limits its theme."""

    effective_sync_mode: SyncMode = SyncMode.SYNC
    #: The library items it holds, in display order; the library lists them.
    member_ids: list[int]
    rule: CollectionRuleRead | None = None
    #: Its criteria include TMDB or MDBList lists, so the library can lack
    #: titles they hold.
    lists_missing: bool = False
    #: Why a theme cannot be stored on this collection, if it cannot.
    theme_unavailable: str | None = None
    theme_writable: bool = False
    catalog_entry_key: str | None = None
    #: The catalog entry's title, when OvertureDB has the TMDB collection.
    catalog_title: str | None = None
    #: The catalog's theme candidates for the collection.
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None


class SetCollectionThemeRequest(StrictBaseModel):
    """Validate the set collection theme request payload."""

    youtube_id: YouTubeId


class SetCollectionThemeResponse(StrictBaseModel):
    """A collection's chosen theme: its queued download, or a choice kept for later."""

    #: ``None`` when the collection is inactive: the sync that puts it back on
    #: the server downloads the theme.
    job_id: str | None
    #: The theme as stored now; a queued video becomes it once downloaded.
    theme: AssetRead


class DeleteCollectionThemeResponse(StatusResponse):
    """Collection theme delete response: the theme as it is now."""

    theme: AssetRead


def _server_image_version(
    row: MediaCollection, kind: ServerAsset, lead: CollectionLibrary | None
) -> str | None:
    """Name the lead copy's current image without revealing its URL."""
    found = (
        delivery(
            read_asset(row, kind),
            Destination(lead.server_id, lead.server_item_id),
        )
        if lead
        else None
    )
    return image_version(found.observed_ref if found else None)


def collection_metadata_issues(row: MediaCollection) -> list[MetadataIssue]:
    """The gaps in a collection's metadata: a TMDB collection and a server copy."""
    found = {
        MetadataIssue.NO_TMDB_ID: row.tmdb_collection_id is None,
        MetadataIssue.NO_SERVER_ID: not row.copies,
    }
    return [issue for issue in MetadataIssue if found.get(issue)]


def collection_read(
    row: MediaCollection,
    catalog: CatalogCollection | None,
    rule: CollectionRule | None,
    *,
    copies: Sequence[CollectionLibrary],
    trust_no_theme: bool,
) -> CollectionRead:
    """Map a stored collection, its catalog entry and its rule to public output.

    *copies* holds a part for each server copy on the configured servers, the
    lead first; *trust_no_theme* lets the catalog's No theme flag count as a
    theme.
    """
    lead = copies[0] if copies else None
    return CollectionRead(
        id=row.id or 0,
        assets=assets_read(row),
        art_status=combined_status(
            read_asset(row, kind).status
            for kind in (ServerAsset.POSTER, ServerAsset.BACKGROUND)
        ),
        kind=row.kind,
        title=row.title,
        summary=row.summary,
        sort_title=row.sort_title,
        sort_title_format=row.sort_title_format,
        summary_format=row.summary_format,
        collection_group=row.group_name,
        collection_mode=row.collection_mode,
        order_type=row.order_type,
        collection_filtering=row.collection_filtering,
        visible_home=row.visible_home,
        visible_shared=row.visible_shared,
        visible_library=row.visible_library,
        active_start_mmdd=row.active_start_mmdd,
        active_end_mmdd=row.active_end_mmdd,
        delete_when_inactive=row.delete_when_inactive,
        withheld=not copies,
        metadata_issues=collection_metadata_issues(row),
        unsynced=row.unsynced,
        managed=rule is not None,
        sync_failed=bool(rule and rule.last_error),
        last_rule_sync=rule.last_synced_at if rule else None,
        generated_value=row.generated_value,
        server_poster_version=_server_image_version(row, ServerAsset.POSTER, lead),
        server_background_version=_server_image_version(
            row, ServerAsset.BACKGROUND, lead
        ),
        child_count=row.child_count,
        media_types=row.media_types,
        library_ids=row.library_ids,
        server_added_at=row.server_added_at.isoformat()
        if row.server_added_at
        else None,
        copies=[
            CollectionCopyRead(
                server_id=copy.server_id,
                server_item_id=copy.server_item_id or "",
                library_ids=[
                    part.library_id
                    for part in row.libraries
                    if (part.server_id, part.server_item_id)
                    == (copy.server_id, copy.server_item_id)
                ],
            )
            for copy in copies
        ],
        monitored=row.monitored,
        tmdb_collection_id=row.tmdb_collection_id,
        catalog_complete=bool(
            catalog
            and (catalog.youtube_id_overturedb or (trust_no_theme and catalog.no_theme))
        ),
        catalog_themerrdb=bool(catalog and catalog.youtube_id_themerrdb),
    )


class BulkCollectionMonitorUpdate(StrictBaseModel):
    """Validate bulk collection monitor updates."""

    collection_ids: CollectionIds
    monitored: bool


class CollectionUpdatedEvent(StrictBaseModel):
    """A collection changed."""

    collection_id: int
    #: Whether the titles it links changed too: its members or its TMDB
    #: collection, which the library lists show. Only then are those lists,
    #: every title of the library, read again.
    titles: bool


class CollectionMonitoredEvent(StrictBaseModel):
    """A collection was monitored or unmonitored; nothing else changed."""

    collection_id: int
    monitored: bool


class CollectionPolicyBase(StrictBaseModel):
    """Shared policy and media server display configuration."""

    sync_mode: SyncMode | None = None
    minimum_items: Annotated[int, Field(ge=1, le=100)] | None = None
    delete_below_minimum: bool | None = None
    #: The sources a sync tries for a slot with no art chosen, first to last.
    auto_art: UniqueList[AutoArtSource] | None = None
    #: The colours of art Overture generates for it automatically.
    generated_style: ArtStyle | None = None
    #: Whether posters generated for it automatically show its title alone,
    #: without its group.
    generated_title_only: bool | None = None
    #: The OvertureDB poster styles it takes, first to last; the first is what
    #: a poster chosen for it is contributed as unless OvertureDB holds it.
    overturedb_posters: UniqueList[CollectionPosterStyle] | None = None
    #: Whether it needs a background; without one, a poster makes its art complete.
    backgrounds: bool | None = None
    #: Whether it needs a theme; without one, its theme is complete as it is.
    themes: bool | None = None
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
    tmdb_collection_id: PositiveId | None = None
    collection_mode: CollectionMode | None = None
    #: Null inherits the group's or the global default.
    order_type: CollectionOrder | None = None
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
    """Create a collection; its rule names the libraries and what each selects."""

    rule: CollectionRuleWrite


class CollectionMembersUpdate(StrictBaseModel):
    """Replace membership and optionally set its display order."""

    member_ids: Annotated[list[PositiveId], Field(max_length=10000)]
    order_type: CollectionOrder


class CollectionLibraryCriteria(StrictBaseModel):
    """What a collection selects from one library."""

    library_id: LibraryId
    criteria: FilterGroup


class CollectionRuleWrite(CollectionPolicyBase):
    """Each library's criteria, which decide membership, and policy overrides."""

    libraries: Annotated[
        list[CollectionLibraryCriteria], Field(min_length=1, max_length=20)
    ]
    #: Plex evaluates the criteria live instead of Overture on each sync.
    smart: bool = False
    #: The most members taken from each library.
    limit: Annotated[int, Field(ge=1, le=10000)] | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        """Require a condition per library, and leave smart ones to Plex's order."""
        ids = [library.library_id for library in self.libraries]
        if len(set(ids)) != len(ids):
            raise ValueError("Give each library one set of criteria")
        if any(library.criteria.is_empty() for library in self.libraries):
            raise ValueError("Add at least one condition for each library")
        if self.smart and self.order_type is CollectionOrder.CUSTOM:
            raise ValueError(SMART_CUSTOM_ORDER)
        return self


class CollectionRuleRead(CollectionRuleWrite):
    """Saved rule with its most recent outcome."""

    last_synced_at: datetime | None = None
    last_error: PublicText | None = None
    #: The description of the first list, which {source_summary} shows.
    source_summary: str | None = None


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
    """Nullable group defaults; null inherits the application setting."""

    generator: CollectionGenerator | None = None
    #: Head the group's collections with an empty one titled after the group;
    #: Plex only, the one server that keeps empty collections.
    separator: bool = False


class CollectionDefaults(CollectionPolicyBase):
    """The values a collection or group inherits, resolved for form placeholders."""


class CollectionAdoption(StrictBaseModel):
    """The group a collection joins when Overture adopts it."""

    group: GroupName | None = None


class CollectionAdoptionPlan(StrictBaseModel):
    """The rule and TMDB collection adopting a collection would save."""

    rule: CollectionRuleWrite
    tmdb_collection_id: int | None


class CollectionGroupRename(StrictBaseModel):
    """A replacement group name, scoped by the request."""

    name: Annotated[GroupName, Field(min_length=1)]


type CollectionDeleteTarget = Literal["server", "both"]


class CollectionGroupDelete(StrictBaseModel):
    """What happens to a deleted group's collections.

    ``keep`` moves them to Ungrouped, ``move`` puts them in *group*,
    ``orphan`` stops managing them, as orphaning one collection does, and
    ``both`` deletes them from Overture and the server.
    """

    collections: Literal["keep", "move", "orphan", "both"] = "keep"
    group: GroupName | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Moving needs a group to move to, and only moving takes one."""
        if (self.collections == "move") != bool(self.group and self.group.strip()):
            raise ValueError("Name the group to move the collections to")
        return self


class CollectionSetPreview(StrictBaseModel):
    """Preview a set's collections in its libraries before saving it."""

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
    #: Another collection in the library already has the title, so a sync
    #: cannot create this one until one of them is renamed.
    title_taken_by: int | None = None


class CollectionSetSummary(StrictBaseModel):
    """A group that is a set: what it splits by, and in which libraries."""

    group: str
    dimension: SetDimension
    library_ids: list[str]


class CollectionMissingTitle(StrictBaseModel):
    """A title a collection's lists hold that the library lacks."""

    tmdb_id: int
    title: str
    year: int | None = None
    poster_url: str | None = None
    media_type: MediaType
    #: Radarr or Sonarr already has it.
    requested: bool = False
    #: Radarr or Sonarr is set up to take it.
    requestable: bool = False


class CollectionMissing(StrictBaseModel):
    """What a collection's lists hold beyond the library."""

    titles: list[CollectionMissingTitle]
    #: More titles are missing than are listed.
    truncated: bool = False
    #: Radarr or Sonarr is set up to take requests for one of its libraries.
    requestable: bool = False


class CollectionRequestTitle(StrictBaseModel):
    """One title to request; TMDB numbers movies and shows apart."""

    tmdb_id: PositiveId
    media_type: MediaType


class CollectionRequest(StrictBaseModel):
    """Titles to request; none requests every missing one."""

    titles: Annotated[list[CollectionRequestTitle], Field(max_length=500)] | None = None


class CollectionRequestResult(StrictBaseModel):
    """What a request added to Radarr or Sonarr."""

    requested: int = 0
    #: Already in Radarr or Sonarr.
    present: int = 0
    errors: list[PublicText] = Field(default_factory=list[PublicText])


class CollectionArrOptions(StrictBaseModel):
    """Where Radarr or Sonarr can put requested titles."""

    root_folders: list[str]
    quality_profiles: list[ArrTagRead]


class KindRecommendation(StrictBaseModel):
    """The collection kind that suits the criteria, and why."""

    kind: CollectionKind
    reason: PublicText


class CollectionLibraryPreview(StrictBaseModel):
    """What one library's criteria select."""

    library_id: str
    member_count: int
    #: The first members, in the collection's order.
    members: list[str]
    #: Titles whose TMDB facts no sync has read yet, when the criteria test them.
    tmdb_unread: int = 0


class CollectionPreview(StrictBaseModel):
    """What a collection's criteria select before it is saved."""

    libraries: list[CollectionLibraryPreview]


class CollectionKindRequest(StrictBaseModel):
    """A rule being edited, to recommend the collection kind for."""

    rule: CollectionRuleWrite


class CollectionPreviewRequest(StrictBaseModel):
    """A rule whose criteria to preview in each of its libraries."""

    rule: CollectionRuleWrite
    #: The saved collection being edited, which never counts as another
    #: collection holding a title.
    collection_id: PositiveId | None = None


class FieldChoice(StrictBaseModel):
    """A value a field can hold and how it is named to people."""

    value: str
    label: str


class CollectionFieldRead(StrictBaseModel):
    """A criteria field as the active server offers it."""

    field: FilterField
    label: str
    kind: FieldKind
    #: The operators Overture evaluates, and those Plex smart collections test.
    operators: list[FilterOperator]
    smart_operators: list[FilterOperator]
    #: Overture can evaluate it from synced metadata.
    local: bool
    #: Plex smart collections can test it.
    smart: bool
    #: Smart collections test it through labels Overture keeps on matching
    #: items, so their members change when Overture syncs, not live.
    labelled: bool = False
    #: The library's own status of a title, which library filters test in
    #: the browser, against the live library list.
    library_status: bool = False
    #: The values the field can hold, when they are a fixed set; otherwise a
    #: tag field holds the values the library lists.
    choices: list[FieldChoice] = Field(default_factory=list[FieldChoice])
    #: Any value can be named, beyond those the library holds, such as an ID.
    free_values: bool = False
    #: Its values are IDs, chosen by the labels the library's values give them.
    by_id: bool = False
    #: Criteria match its values ignoring case, so "drama" matches "Drama".
    ignores_case: bool = False

    @classmethod
    def of(
        cls,
        field: FilterField,
        server: ServerType,
        *,
        local: bool = True,
        smart: bool = False,
        labelled: bool = False,
    ) -> Self:
        """Describe *field* as *server* names it, with how it can be tested."""
        spec = FIELDS[field]
        return cls(
            field=field,
            label=field_label(field, server),
            kind=spec.kind,
            operators=list(field_operators(field, smart=False)),
            smart_operators=list(field_operators(field, smart=True)) if smart else [],
            local=local,
            smart=smart,
            labelled=labelled,
            library_status=spec.library_only,
            choices=[
                FieldChoice(value=value, label=label) for value, label in spec.choices
            ],
            free_values=spec.free,
            by_id=spec.by_id,
            ignores_case=spec.kind.ignores_case,
        )


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
    #: What a new set of it starts with: the text its values' names drop, and
    #: the order its collections inherit from the group.
    strip_prefix: str = ""
    strip_suffix: str = ""
    order_type: CollectionOrder | None = None


class CollectionCapabilities(StrictBaseModel):
    """What collections of one media type can do on some media servers.

    A collection spanning several servers is offered what any of them
    supports; each of the others falls back to its nearest.
    """

    #: The kinds of the servers described.
    server_types: list[ServerType]
    #: One server collection can hold several libraries, of either media type,
    #: on every server described.
    spans_libraries: bool
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


class MdblistListRead(StrictBaseModel):
    """A public MDBList list a search found."""

    id: int
    name: str
    #: The MDBList user who keeps it.
    owner: str | None = None
    #: How many titles it holds.
    items: int | None = None


class CollectionFieldValue(StrictBaseModel):
    """A value of a field in a library, with the number of items holding it."""

    #: What criteria hold, such as a collection's ID.
    value: str
    #: How the value is named to people, such as a collection's title.
    label: str
    count: int


class BulkCollectionOperation(StrictBaseModel):
    """One bounded operation over an explicit collection selection."""

    collection_ids: CollectionIds
    operation: Literal[
        "set_visibility",
        "set_order",
        "set_monitored",
        "set_group",
        "apply_sort_title_format",
        "adopt",
        "orphan",
        "remove_artwork",
        "remove_themes",
        "delete",
    ]
    collection_mode: CollectionMode | None = None
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    #: The order ``set_order`` gives; null inherits the group's or global default.
    order_type: CollectionOrder | None = None
    monitored: bool | None = None
    collection_group: GroupName | None = None
    sort_title_format: SortTitleFormat | None = None
    #: Where ``delete`` removes the collections from.
    delete_target: CollectionDeleteTarget = "both"
    #: What ``remove_artwork`` and ``remove_themes`` remove.
    removal: AssetRemoval = Field(default_factory=AssetRemoval)

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        """Reject missing operation arguments before any server writes."""
        if len(set(self.collection_ids)) != len(self.collection_ids):
            raise ValueError("Select distinct collections")
        required = {
            "set_monitored": self.monitored,
            "apply_sort_title_format": self.sort_title_format,
        }
        if self.operation in required and required[self.operation] is None:
            raise ValueError("The operation requires a value")
        # A null order inherits the group's or the global default.
        if self.operation == "set_order" and "order_type" not in self.model_fields_set:
            raise ValueError("Choose a sort")
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
    errors: dict[int, PublicText] = Field(default_factory=dict[int, PublicText])
    #: Collections left as they were, and why.
    skipped: dict[int, str] = Field(default_factory=dict[int, str])
