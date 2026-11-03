"""Starting points for collections and collection sets, like Kometa's defaults."""

lazy from dataclasses import dataclass, field
lazy from string import ascii_uppercase

lazy from ...db.models.collection_preset import CollectionPreset
lazy from ...domain import (
    CollectionFiltering,
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    ServerType,
    SetDimension,
    TmdbChart,
)
lazy from ...integrations.tmdb import chart_available
lazy from ...schemas.collections import (
    CollectionGeneratorBase,
    CollectionPolicyBase,
    CollectionPresetCollection,
    CollectionPresetRead,
    CollectionPresetSave,
    CollectionPresetSet,
    CollectionRuleWrite,
    CustomSetValue,
    FieldCondition,
    FilterGroup,
    SourceCondition,
    TmdbChartSource,
)
lazy from .fields import (
    DIMENSIONS,
    FIELDS,
    available_orders,
    dimension_available,
    field_available,
)


def _is(field: FilterField, value: str | int | bool) -> FieldCondition:
    return FieldCondition(field=field, operator=FilterOperator.IS, value=value)


def _keyword(name: str) -> FilterGroup:
    return FilterGroup(conditions=[_is(FilterField.TMDB_KEYWORD, name)])


def _chart(chart: TmdbChart, limit: int) -> FilterGroup:
    return FilterGroup(
        conditions=[SourceCondition(source=TmdbChartSource(chart=chart, limit=limit))]
    )


@dataclass(slots=True, frozen=True)
class _CollectionPreset:
    key: str
    label: str
    description: str
    criteria: FilterGroup
    order: CollectionOrder
    limit: int | None = None
    #: Plex keeps it current for each user as a smart collection.
    per_user: bool = False
    #: Active each year between these dates, and removed from the server outside.
    season: tuple[str, str] | None = None
    media_types: frozenset[MediaType] = frozenset(MediaType)


@dataclass(slots=True, frozen=True)
class _SetPreset:
    key: str
    description: str
    dimension: SetDimension
    top: int | None = None
    policy: CollectionPolicyBase = field(default_factory=CollectionPolicyBase)
    strip_prefix: str = ""
    strip_suffix: str = ""
    #: Named after the dimension unless given.
    label: str | None = None
    custom_values: tuple[CustomSetValue, ...] = ()
    #: Plex evaluates the set's collections, for fields only Plex knows.
    smart: bool = False


_MOVIES = frozenset({MediaType.MOVIE})
_SHOWS = frozenset({MediaType.SHOW})


def _holiday(
    key: str, label: str, keyword: str, start: str, end: str
) -> _CollectionPreset:
    return _CollectionPreset(
        key,
        label,
        f"Titles TMDB tags {keyword}, shown from {start} to {end} each year.",
        _keyword(keyword),
        CollectionOrder.RELEASE_ASC,
        season=(start, end),
    )


_COLLECTIONS = (
    _CollectionPreset(
        "recently_added",
        "Recently added",
        "Titles added in the last 30 days, newest first.",
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.ADDED, operator=FilterOperator.IN_LAST, value=30
                )
            ]
        ),
        CollectionOrder.ADDED_DESC,
    ),
    _CollectionPreset(
        "recently_released",
        "Recently released",
        "Titles released in the last 90 days, newest first.",
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.RELEASED,
                    operator=FilterOperator.IN_LAST,
                    value=90,
                )
            ]
        ),
        CollectionOrder.RELEASE_DESC,
    ),
    _CollectionPreset(
        "highly_rated",
        "Highly rated",
        "The 100 titles critics rate highest, from 8 out of 10.",
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.CRITIC_RATING,
                    operator=FilterOperator.GTE,
                    value=8,
                )
            ]
        ),
        CollectionOrder.CRITIC_RATING_DESC,
        limit=100,
    ),
    _CollectionPreset(
        "most_played",
        "Most played",
        "The 25 most played titles among those played in the last 90 days.",
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.LAST_PLAYED,
                    operator=FilterOperator.IN_LAST,
                    value=90,
                )
            ]
        ),
        CollectionOrder.PLAYS_DESC,
        limit=25,
    ),
    _CollectionPreset(
        "unplayed",
        "Unplayed",
        "What each user has not played yet, newest additions first.",
        FilterGroup(conditions=[_is(FilterField.UNPLAYED, True)]),
        CollectionOrder.ADDED_DESC,
        per_user=True,
    ),
    _CollectionPreset(
        "continue_watching",
        "Continue watching",
        "What each user has started, most recently played first.",
        FilterGroup(conditions=[_is(FilterField.IN_PROGRESS, True)]),
        CollectionOrder.LAST_PLAYED_DESC,
        per_user=True,
    ),
    _CollectionPreset(
        "recently_played",
        "Recently played",
        "What each user played in the last 30 days.",
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.LAST_PLAYED,
                    operator=FilterOperator.IN_LAST,
                    value=30,
                )
            ]
        ),
        CollectionOrder.LAST_PLAYED_DESC,
        per_user=True,
    ),
    _CollectionPreset(
        "4k",
        "4K",
        "Every title available in 4K.",
        FilterGroup(conditions=[_is(FilterField.RESOLUTION, "4k")]),
        CollectionOrder.TITLE_ASC,
    ),
    _CollectionPreset(
        "short",
        "Short films",
        "Films of an hour or less.",
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.DURATION, operator=FilterOperator.LTE, value=60
                )
            ]
        ),
        CollectionOrder.TITLE_ASC,
    ),
    _CollectionPreset(
        "tmdb_popular",
        "Popular",
        "TMDB's 50 most popular titles that are in the library, in chart order.",
        _chart(TmdbChart.POPULAR, 50),
        CollectionOrder.CUSTOM,
    ),
    _CollectionPreset(
        "tmdb_trending",
        "Trending",
        "What is trending on TMDB this week, in chart order.",
        _chart(TmdbChart.TRENDING_WEEK, 50),
        CollectionOrder.CUSTOM,
    ),
    _CollectionPreset(
        "tmdb_top_rated",
        "TMDB top rated",
        "The library's titles among TMDB's 250 top rated, in chart order.",
        _chart(TmdbChart.TOP_RATED, 250),
        CollectionOrder.CUSTOM,
    ),
    _CollectionPreset(
        "in_cinemas",
        "In cinemas",
        "Movies TMDB lists as now playing in cinemas in your region.",
        _chart(TmdbChart.NOW_PLAYING, 100),
        CollectionOrder.CUSTOM,
        media_types=_MOVIES,
    ),
    _CollectionPreset(
        "airing_this_week",
        "Airing this week",
        "Shows with an episode airing in the next seven days.",
        _chart(TmdbChart.ON_THE_AIR, 200),
        CollectionOrder.CUSTOM,
        media_types=_SHOWS,
    ),
    _CollectionPreset(
        "returning",
        "Returning series",
        "Shows TMDB lists as still returning with new seasons.",
        FilterGroup(conditions=[_is(FilterField.SHOW_STATUS, "Returning Series")]),
        CollectionOrder.TITLE_ASC,
        media_types=_SHOWS,
    ),
    _CollectionPreset(
        "mcu",
        "Marvel Cinematic Universe",
        "Titles TMDB tags as part of the Marvel Cinematic Universe, in release order.",
        _keyword("marvel cinematic universe (mcu)"),
        CollectionOrder.RELEASE_ASC,
    ),
    _CollectionPreset(
        "dceu",
        "DC Extended Universe",
        "Titles TMDB tags as part of the DC Extended Universe, in release order.",
        _keyword("dc extended universe (dceu)"),
        CollectionOrder.RELEASE_ASC,
    ),
    _holiday("christmas", "Christmas", "christmas", "12-01", "12-31"),
    _holiday("halloween", "Halloween", "halloween", "10-01", "10-31"),
    _holiday("thanksgiving", "Thanksgiving", "thanksgiving", "11-01", "11-30"),
    _holiday("valentines", "Valentine's Day", "valentine's day", "02-01", "02-14"),
)

_PEOPLE = CollectionPolicyBase(minimum_items=3)
_FEW = CollectionPolicyBase(minimum_items=5)


def _letter(letter: str) -> CustomSetValue:
    return CustomSetValue(
        name=letter,
        criteria=FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.TITLE,
                    operator=FilterOperator.STARTS_WITH,
                    value=letter,
                )
            ]
        ),
    )


_ALPHABET = (
    *(_letter(letter) for letter in ascii_uppercase),
    CustomSetValue(
        name="#",
        criteria=FilterGroup(
            mode="any",
            conditions=[
                FieldCondition(
                    field=FilterField.TITLE,
                    operator=FilterOperator.STARTS_WITH,
                    value=str(digit),
                )
                for digit in range(10)
            ],
        ),
    ),
)
_BASED_ON = tuple(
    CustomSetValue(name=name, criteria=_keyword(keyword))
    for name, keyword in (
        ("Based on a book", "based on novel or book"),
        ("Based on a true story", "based on true story"),
        ("Based on a comic", "based on comic"),
        ("Based on a video game", "based on video game"),
        ("Based on a play", "based on play or musical"),
    )
)

_SETS = (
    _SetPreset("decades", "One collection per decade.", SetDimension.DECADE),
    _SetPreset("years", "One collection per release year.", SetDimension.YEAR),
    _SetPreset("genres", "One collection per genre.", SetDimension.GENRE),
    _SetPreset(
        "studios",
        "The 25 studios with the most titles.",
        SetDimension.STUDIO,
        top=25,
        policy=_PEOPLE,
    ),
    _SetPreset(
        "networks",
        "The 25 networks with the most shows.",
        SetDimension.NETWORK,
        top=25,
        policy=_PEOPLE,
    ),
    _SetPreset(
        "countries", "One collection per production country.", SetDimension.COUNTRY
    ),
    _SetPreset(
        "origin_countries",
        "One collection per country of origin, from TMDB.",
        SetDimension.ORIGIN_COUNTRY,
        policy=_FEW,
    ),
    _SetPreset(
        "original_languages",
        "One collection per original language, from TMDB.",
        SetDimension.ORIGINAL_LANGUAGE,
        policy=_FEW,
    ),
    _SetPreset(
        "audio_languages",
        "One Plex smart collection per audio language.",
        SetDimension.AUDIO_LANGUAGE,
        policy=_FEW,
        smart=True,
    ),
    _SetPreset(
        "subtitle_languages",
        "One Plex smart collection per subtitle language.",
        SetDimension.SUBTITLE_LANGUAGE,
        policy=_FEW,
        smart=True,
    ),
    _SetPreset(
        "streaming",
        "One collection per subscription service streaming the titles in your "
        "region, from TMDB.",
        SetDimension.STREAMING,
        policy=_FEW,
    ),
    _SetPreset(
        "content_ratings",
        "One collection per content rating.",
        SetDimension.CONTENT_RATING,
    ),
    _SetPreset(
        "resolutions", "One collection per video resolution.", SetDimension.RESOLUTION
    ),
    _SetPreset(
        "editions",
        "One collection per edition, such as Director's Cut.",
        SetDimension.EDITION,
    ),
    _SetPreset(
        "actors",
        "The 25 actors with the most titles.",
        SetDimension.ACTOR,
        top=25,
        policy=_PEOPLE,
    ),
    _SetPreset(
        "directors",
        "The 25 directors with the most titles.",
        SetDimension.DIRECTOR,
        top=25,
        policy=_PEOPLE,
    ),
    _SetPreset(
        "writers",
        "The 25 writers with the most titles.",
        SetDimension.WRITER,
        top=25,
        policy=_PEOPLE,
    ),
    _SetPreset("labels", "One collection per label.", SetDimension.LABEL),
    _SetPreset(
        "franchises",
        "One collection per TMDB franchise with at least two titles in the "
        "library, kept in release order.",
        SetDimension.FRANCHISE,
        policy=CollectionPolicyBase(
            minimum_items=2,
            order_type=CollectionOrder.RELEASE_ASC,
        ),
        strip_prefix="The ",
        strip_suffix=" Collection",
    ),
    _SetPreset(
        "based_on",
        "Books, true stories, comics, video games and plays, from TMDB keywords.",
        SetDimension.CUSTOM,
        policy=_FEW,
        label="Based on",
        custom_values=_BASED_ON,
    ),
    _SetPreset(
        "alphabet",
        "One collection per first letter of the title, and # for digits.",
        SetDimension.CUSTOM,
        label="A to Z",
        custom_values=_ALPHABET,
        policy=CollectionPolicyBase(order_type=CollectionOrder.TITLE_ASC),
    ),
)


def _needs_tmdb(criteria: FilterGroup) -> bool:
    return any(FIELDS[c.field].tmdb for c in criteria.field_conditions()) or any(
        c.source.type.startswith("tmdb") for c in criteria.source_conditions()
    )


def _criteria_available(
    criteria: FilterGroup,
    server: ServerType,
    media_type: MediaType,
    *,
    smart: bool,
    tmdb: bool,
) -> bool:
    return (
        (tmdb or not _needs_tmdb(criteria))
        and all(
            field_available(c.field, server, media_type, smart=smart)
            for c in criteria.field_conditions()
        )
        and all(
            not isinstance(c.source, TmdbChartSource)
            or chart_available(media_type, c.source.chart)
            for c in criteria.source_conditions()
        )
    )


def _collection(
    preset: _CollectionPreset, server: ServerType, media_type: MediaType, *, tmdb: bool
) -> CollectionPresetRead | None:
    smart = server is ServerType.PLEX and preset.per_user
    if media_type not in preset.media_types or not _criteria_available(
        preset.criteria, server, media_type, smart=smart, tmdb=tmdb
    ):
        return None
    start, end = preset.season or (None, None)
    return CollectionPresetRead(
        key=preset.key,
        label=preset.label,
        description=preset.description,
        collection=CollectionPresetCollection(
            title=preset.label,
            collection_filtering=CollectionFiltering.USER if smart else None,
            rule=CollectionRuleWrite(
                criteria=preset.criteria,
                smart=smart,
                # A server that cannot keep the chart's order uses its default.
                order_type=preset.order
                if preset.order in available_orders(server, media_type, smart=smart)
                else None,
                limit=preset.limit,
                active_start_mmdd=start,
                active_end_mmdd=end,
                delete_when_inactive=True if preset.season else None,
            ),
        ),
    )


def _set(
    preset: _SetPreset, server: ServerType, media_type: MediaType, *, tmdb: bool
) -> CollectionPresetRead | None:
    spec = DIMENSIONS[preset.dimension]
    smart = preset.smart and server is ServerType.PLEX
    field = spec.field
    if not dimension_available(preset.dimension, server, media_type, smart=smart):
        return None
    if not tmdb and (
        preset.dimension is SetDimension.FRANCHISE
        or (field is not None and FIELDS[field].tmdb)
        or any(_needs_tmdb(value.criteria) for value in preset.custom_values)
    ):
        return None
    if not all(
        _criteria_available(value.criteria, server, media_type, smart=False, tmdb=tmdb)
        for value in preset.custom_values
    ):
        return None
    label = preset.label or spec.label
    return CollectionPresetRead(
        key=preset.key,
        label=label,
        description=preset.description,
        set=CollectionPresetSet(
            group=label,
            policy=preset.policy,
            generator=CollectionGeneratorBase(
                dimension=preset.dimension,
                top=preset.top,
                title_format=spec.title_format,
                strip_prefix=preset.strip_prefix,
                strip_suffix=preset.strip_suffix,
                custom_values=list(preset.custom_values),
                smart=smart,
            ),
        ),
    )


def available_presets(
    server: ServerType, media_type: MediaType, *, tmdb: bool
) -> list[CollectionPresetRead]:
    """The presets the server can evaluate for the media type, sets first.

    Presets that read TMDB are offered only with a TMDB API key.
    """
    sets = [
        read
        for preset in _SETS
        if (read := _set(preset, server, media_type, tmdb=tmdb)) is not None
    ]
    collections = [
        read
        for preset in _COLLECTIONS
        if (read := _collection(preset, server, media_type, tmdb=tmdb)) is not None
    ]
    return [*sets, *collections]


def saved_preset_read(row: CollectionPreset) -> CollectionPresetRead:
    """A preset saved from the form, as the preset list offers it."""
    saved = CollectionPresetSave.model_validate_json(row.payload_json)
    return CollectionPresetRead(
        key=f"saved:{row.id}",
        label=row.label,
        description=row.description,
        collection=saved.collection,
        set=saved.set,
        saved_id=row.id,
    )
