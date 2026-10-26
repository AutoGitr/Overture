"""Starting points for collections and collection sets, like Kometa's defaults."""

lazy from dataclasses import dataclass, field

lazy from ...domain import (
    CollectionFiltering,
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    ServerType,
    SetDimension,
)
lazy from ...schemas.collections import (
    CollectionGeneratorBase,
    CollectionPolicyBase,
    CollectionPresetCollection,
    CollectionPresetRead,
    CollectionPresetSet,
    CollectionRuleWrite,
    FieldCondition,
    FilterGroup,
)
lazy from .fields import DIMENSIONS, dimension_available, field_available


@dataclass(slots=True, frozen=True)
class _CollectionPreset:
    key: str
    label: str
    description: str
    conditions: tuple[tuple[FilterField, FilterOperator, str | int | bool], ...]
    order: CollectionOrder
    limit: int | None = None
    #: Plex keeps it current for each user as a smart collection.
    per_user: bool = False


@dataclass(slots=True, frozen=True)
class _SetPreset:
    key: str
    description: str
    dimension: SetDimension
    top: int | None = None
    policy: CollectionPolicyBase = field(default_factory=CollectionPolicyBase)
    strip_prefix: str = ""
    strip_suffix: str = ""


_COLLECTIONS = (
    _CollectionPreset(
        "recently_added",
        "Recently added",
        "Titles added in the last 30 days, newest first.",
        ((FilterField.ADDED, FilterOperator.IN_LAST, 30),),
        CollectionOrder.ADDED_DESC,
    ),
    _CollectionPreset(
        "recently_released",
        "Recently released",
        "Titles released in the last 90 days, newest first.",
        ((FilterField.RELEASED, FilterOperator.IN_LAST, 90),),
        CollectionOrder.RELEASE_DESC,
    ),
    _CollectionPreset(
        "top_rated",
        "Top rated",
        "The 100 titles critics rate highest, from 8 out of 10.",
        ((FilterField.CRITIC_RATING, FilterOperator.GTE, 8),),
        CollectionOrder.CRITIC_RATING_DESC,
        limit=100,
    ),
    _CollectionPreset(
        "unplayed",
        "Unplayed",
        "What each user has not played yet, newest additions first.",
        ((FilterField.UNPLAYED, FilterOperator.IS, True),),
        CollectionOrder.ADDED_DESC,
        per_user=True,
    ),
    _CollectionPreset(
        "continue_watching",
        "Continue watching",
        "What each user has started, most recently played first.",
        ((FilterField.IN_PROGRESS, FilterOperator.IS, True),),
        CollectionOrder.LAST_PLAYED_DESC,
        per_user=True,
    ),
    _CollectionPreset(
        "recently_played",
        "Recently played",
        "What each user played in the last 30 days.",
        ((FilterField.LAST_PLAYED, FilterOperator.IN_LAST, 30),),
        CollectionOrder.LAST_PLAYED_DESC,
        per_user=True,
    ),
    _CollectionPreset(
        "4k",
        "4K",
        "Every title available in 4K.",
        ((FilterField.RESOLUTION, FilterOperator.IS, "4k"),),
        CollectionOrder.TITLE_ASC,
    ),
    _CollectionPreset(
        "short",
        "Short films",
        "Films of an hour or less.",
        ((FilterField.DURATION, FilterOperator.LTE, 60),),
        CollectionOrder.TITLE_ASC,
    ),
)

_PEOPLE = CollectionPolicyBase(minimum_items=3)

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
        "countries", "One collection per production country.", SetDimension.COUNTRY
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
        "library, kept in release order. Requires a TMDB API key.",
        SetDimension.FRANCHISE,
        policy=CollectionPolicyBase(
            minimum_items=2,
            order_type=CollectionOrder.RELEASE_ASC,
        ),
        strip_prefix="The ",
        strip_suffix=" Collection",
    ),
)


def _collection(
    preset: _CollectionPreset, server: ServerType, media_type: MediaType
) -> CollectionPresetRead | None:
    smart = server is ServerType.PLEX and preset.per_user
    if not all(
        field_available(field, server, media_type, smart=smart)
        for field, _, _ in preset.conditions
    ):
        return None
    return CollectionPresetRead(
        key=preset.key,
        label=preset.label,
        description=preset.description,
        collection=CollectionPresetCollection(
            title=preset.label,
            collection_filtering=CollectionFiltering.USER if smart else None,
            rule=CollectionRuleWrite(
                criteria=FilterGroup(
                    conditions=[
                        FieldCondition(field=field, operator=operator, value=value)
                        for field, operator, value in preset.conditions
                    ]
                ),
                smart=smart,
                order_type=preset.order,
                limit=preset.limit,
            ),
        ),
    )


def available_presets(
    server: ServerType, media_type: MediaType
) -> list[CollectionPresetRead]:
    """The presets the server can evaluate for the media type, sets first."""
    sets = [
        CollectionPresetRead(
            key=preset.key,
            label=DIMENSIONS[preset.dimension].label,
            description=preset.description,
            set=CollectionPresetSet(
                group=DIMENSIONS[preset.dimension].label,
                policy=preset.policy,
                generator=CollectionGeneratorBase(
                    dimension=preset.dimension,
                    top=preset.top,
                    title_format=DIMENSIONS[preset.dimension].title_format,
                    strip_prefix=preset.strip_prefix,
                    strip_suffix=preset.strip_suffix,
                ),
            ),
        )
        for preset in _SETS
        if dimension_available(preset.dimension, server, media_type)
    ]
    collections = [
        read
        for preset in _COLLECTIONS
        if (read := _collection(preset, server, media_type)) is not None
    ]
    return [*sets, *collections]
