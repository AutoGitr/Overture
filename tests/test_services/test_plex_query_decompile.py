"""Plex smart filters read back into the criteria that compile to them."""

lazy import pytest

lazy from overture.domain import (
    CollectionOrder,
    FieldKind,
    FilterField,
    FilterOperator,
    MediaType,
)
lazy from overture.schemas.collections import FieldCondition, FilterGroup
lazy from overture.services.collections.plex_query import (
    UnmappableFilterError,
    choice_keys,
    compile_plex_query,
    decompile_plex_query,
    plex_field,
)
lazy from overture.utils.collection_fields import FIELDS

_VALUES: dict[FieldKind, tuple[FilterOperator, str | int | bool]] = {
    FieldKind.TEXT: (FilterOperator.STARTS_WITH, "Alien"),
    FieldKind.TAG: (FilterOperator.IS, "Action"),
    FieldKind.NUMBER: (FilterOperator.GTE, 7),
    FieldKind.DATE: (FilterOperator.IN_LAST, 30),
    FieldKind.BOOLEAN: (FilterOperator.IS, True),
}

_CASES = [
    (field, media_type)
    for field, spec in FIELDS.items()
    if spec.plex is not None and spec.plex.filterable
    for media_type in sorted(spec.media_types)
]


def _round_trip(criteria: FilterGroup, media_type: MediaType) -> FilterGroup:
    tags = {
        plex_field(condition.field).key_for(media_type)
        for condition in criteria.field_conditions()
        if plex_field(condition.field).type == "tag"
    }
    query = compile_plex_query(
        criteria,
        media_type=media_type,
        order=CollectionOrder.ADDED_DESC,
        limit=25,
        choices={key: choice_keys([("12", "Action")]) for key in tags},
        labels={},
    )
    decompiled = decompile_plex_query(
        query, media_type=media_type, names={key: {"12": "Action"} for key in tags}
    )
    assert (decompiled.order, decompiled.limit) == (CollectionOrder.ADDED_DESC, 25)
    return decompiled.criteria


@pytest.mark.parametrize(("field", "media_type"), _CASES)
def test_every_compilable_field_reads_back_as_written(
    field: FilterField, media_type: MediaType
) -> None:
    operator, value = _VALUES[FIELDS[field].kind]
    if FIELDS[field].kind is FieldKind.TEXT and plex_field(field).type == "tag":
        operator = FilterOperator.IS
    if plex_field(field).keyed:
        value = "12"
    if field is FilterField.DECADE:
        # A decade compiles to a year range; only "is" reads back as a decade.
        operator, value = FilterOperator.IS, 1990
    criteria = FilterGroup(
        conditions=[FieldCondition(field=field, operator=operator, value=value)]
    )

    assert _round_trip(criteria, media_type) == criteria


def test_groups_decades_and_negated_tags_read_back() -> None:
    criteria = FilterGroup(
        mode="any",
        conditions=[
            FieldCondition(
                field=FilterField.DECADE, operator=FilterOperator.IS, value=1990
            ),
            FieldCondition(
                field=FilterField.GENRE, operator=FilterOperator.IS_NOT, value="Action"
            ),
        ],
        groups=[
            FilterGroup(
                conditions=[
                    FieldCondition(field=FilterField.TITLE, value="Alien"),
                    FieldCondition(
                        field=FilterField.RELEASED,
                        operator=FilterOperator.BEFORE,
                        value="2001-02-03",
                    ),
                ]
            )
        ],
    )

    assert _round_trip(criteria, MediaType.MOVIE) == criteria


def test_unmappable_filters_are_listed() -> None:
    with pytest.raises(UnmappableFilterError) as raised:
        decompile_plex_query(
            "sort=titleSort&unknownField%3D=1&genre=99",
            media_type=MediaType.MOVIE,
            names={"genre": {"12": "Action"}},
        )
    assert raised.value.terms == ["unknownField==1", "genre=99"]


@pytest.mark.parametrize(
    ("query", "unplayed"),
    [("unwatched=1", True), ("unwatched%21=1", False), ("unwatched=0", False)],
)
def test_booleans_read_back_as_plex_and_overture_write_them(
    query: str, *, unplayed: bool
) -> None:
    decompiled = decompile_plex_query(query, media_type=MediaType.MOVIE, names={})

    assert decompiled.criteria.conditions == [
        FieldCondition(field=FilterField.UNPLAYED, value=unplayed)
    ]


def test_resolutions_read_back_as_the_keys_sync_stores() -> None:
    decompiled = decompile_plex_query(
        "resolution=4k",
        media_type=MediaType.MOVIE,
        names={"resolution": {"4k": "4K", "1080": "1080p"}},
    )

    assert decompiled.criteria.conditions == [
        FieldCondition(field=FilterField.RESOLUTION, value="4k")
    ]


@pytest.mark.parametrize(
    "operator",
    [
        FilterOperator.IS,
        FilterOperator.IS_NOT,
        FilterOperator.GT,
        FilterOperator.GTE,
        FilterOperator.LT,
        FilterOperator.LTE,
    ],
)
def test_whole_minutes_compile_to_plex_milliseconds_and_back(
    operator: FilterOperator,
) -> None:
    criteria = FilterGroup(
        conditions=[
            FieldCondition(field=FilterField.DURATION, operator=operator, value=5)
        ]
    )

    decompiled = _round_trip(criteria, MediaType.MOVIE)

    # "Greater than 5" is "at least 6" in whole minutes, and so on.
    shifted = {
        FilterOperator.GT: (FilterOperator.GTE, 6),
        FilterOperator.LTE: (FilterOperator.LT, 6),
    }
    expected_operator, expected_value = shifted.get(operator, (operator, 5))
    assert decompiled.conditions == [
        FieldCondition(
            field=FilterField.DURATION, operator=expected_operator, value=expected_value
        )
    ]


def test_five_minutes_is_any_duration_up_to_six() -> None:
    query = compile_plex_query(
        FilterGroup(
            conditions=[
                FieldCondition(
                    field=FilterField.DURATION, operator=FilterOperator.IS, value=5
                )
            ]
        ),
        media_type=MediaType.MOVIE,
        order=CollectionOrder.TITLE_ASC,
        limit=None,
        choices={},
        labels={},
    )

    assert query.endswith("push=1&duration%3E=300000&and=1&duration%3C%3C=360000&pop=1")


def test_show_filters_plex_web_scopes_to_the_show_read_back() -> None:
    decompiled = decompile_plex_query(
        "show.title=War&show.unwatchedLeaves=1&show.actor=337778&show.title%21=Staged",
        media_type=MediaType.SHOW,
        names={"actor": {"337778": "Michael Palin"}},
    )

    assert decompiled.criteria.conditions == [
        FieldCondition(
            field=FilterField.TITLE, operator=FilterOperator.CONTAINS, value="War"
        ),
        FieldCondition(field=FilterField.UNPLAYED, value=True),
        FieldCondition(field=FilterField.ACTOR, value="Michael Palin"),
        FieldCondition(
            field=FilterField.TITLE,
            operator=FilterOperator.DOES_NOT_CONTAIN,
            value="Staged",
        ),
    ]
