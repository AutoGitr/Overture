"""Criteria evaluation, member order, Plex queries, sets and presets."""

lazy from collections import Counter
lazy from datetime import UTC, datetime

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import (
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    ServerType,
    SetDimension,
)
lazy from overture.schemas.collections import (
    CollectionGeneratorBase,
    CollectionRuleWrite,
    FieldCondition,
    FilterGroup,
    MdblistSource,
    SourceCondition,
    TmdbCollectionSource,
)
lazy from overture.services.collections.criteria import (
    CriteriaContext,
    evaluate,
    order_items,
)
lazy from overture.services.collections.fields import (
    available_orders,
    dimension_available,
    field_available,
    field_label,
)
lazy from overture.services.collections.plex_query import (
    choice_keys,
    compile_plex_query,
    tag_keys,
)
lazy from overture.services.collections.presets import available_presets
lazy from overture.services.collections.sets import count_values, set_values

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _item(item_id: int = 1, **kwargs: object) -> MediaItem:
    values: dict[str, object] = {
        "id": item_id,
        "media_type": MediaType.MOVIE,
        "title": "Star Wars",
        "year": 1977,
        "release_date": "1977-05-25",
        "critic_rating": 8.6,
        "duration_minutes": 121,
        "studio": "Lucasfilm",
        "director": "George Lucas",
        "content_rating": "PG",
        "resolution": "4k",
        "genres": ["Action", "Sci-Fi"],
        "actors": ["Mark Hamill"],
        "countries": ["United States of America"],
        "labels": ["Classic"],
        "plays": 0,
        "unplayed": True,
        "server_added_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    values.update(kwargs)
    return MediaItem(**values)


def _field(
    field: FilterField, operator: FilterOperator, value: str | float | bool
) -> FieldCondition:
    return FieldCondition(field=field, operator=operator, value=value)


def _context(
    sources: dict[str, frozenset[int]] | None = None,
    collections: dict[int, list[str]] | None = None,
) -> CriteriaContext:
    return CriteriaContext(
        sources=sources or {}, collections=collections or {}, now=NOW
    )


def _matches(item: MediaItem, *conditions: FieldCondition, mode: str = "all") -> bool:
    group = FilterGroup.model_validate(
        {"mode": mode, "conditions": [c.model_dump() for c in conditions]}
    )
    return evaluate([item], group, _context()) == [item]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (_field(FilterField.TITLE, FilterOperator.IS, "star wars"), True),
        (_field(FilterField.TITLE, FilterOperator.IS_NOT, "Star Wars"), False),
        (_field(FilterField.TITLE, FilterOperator.CONTAINS, "WARS"), True),
        (_field(FilterField.TITLE, FilterOperator.DOES_NOT_CONTAIN, "trek"), True),
        (_field(FilterField.TITLE, FilterOperator.STARTS_WITH, "star"), True),
        (_field(FilterField.TITLE, FilterOperator.ENDS_WITH, "wars"), True),
        (_field(FilterField.GENRE, FilterOperator.IS, "sci-fi"), True),
        (_field(FilterField.GENRE, FilterOperator.IS_NOT, "Action"), False),
        (_field(FilterField.DIRECTOR, FilterOperator.IS, "George Lucas"), True),
        (_field(FilterField.CONTENT_RATING, FilterOperator.IS, "PG-13"), False),
        (_field(FilterField.YEAR, FilterOperator.GTE, 1977), True),
        (_field(FilterField.YEAR, FilterOperator.GT, 1977), False),
        (_field(FilterField.DECADE, FilterOperator.IS, 1970), True),
        (_field(FilterField.CRITIC_RATING, FilterOperator.LT, 9), True),
        (_field(FilterField.AUDIENCE_RATING, FilterOperator.IS_NOT, 5), True),
        (_field(FilterField.DURATION, FilterOperator.LTE, 120), False),
        (_field(FilterField.ADDED, FilterOperator.IN_LAST, 30), True),
        (_field(FilterField.ADDED, FilterOperator.NOT_IN_LAST, 30), False),
        (_field(FilterField.RELEASED, FilterOperator.BEFORE, "1980-01-01"), True),
        (_field(FilterField.RELEASED, FilterOperator.AFTER, "1977-05-25"), False),
        (_field(FilterField.LAST_PLAYED, FilterOperator.IN_LAST, 30), False),
        (_field(FilterField.UNPLAYED, FilterOperator.IS, True), True),
        (_field(FilterField.IN_PROGRESS, FilterOperator.IS_NOT, True), True),
    ],
)
def test_field_conditions_match_synced_metadata(
    condition: FieldCondition, expected: bool
) -> None:
    assert _matches(_item(), condition) is expected


def test_groups_combine_conditions_sources_and_collections() -> None:
    first, second = _item(1), _item(2, title="Alien", genres=["Horror"], year=1979)
    franchise = SourceCondition(source=TmdbCollectionSource(collection_id=10))
    excluded = SourceCondition(
        operator=FilterOperator.IS_NOT, source=MdblistSource(identifiers=["a/b"])
    )
    criteria = FilterGroup(
        mode="any",
        conditions=[franchise],
        groups=[
            FilterGroup(
                conditions=[
                    _field(FilterField.COLLECTION, FilterOperator.IS, "Favourites"),
                    excluded,
                ]
            )
        ],
    )
    context = _context(
        sources={franchise.key: frozenset({1}), excluded.key: frozenset({1})},
        collections={2: ["Favourites"]},
    )
    assert evaluate([first, second], criteria, context) == [first, second]
    assert criteria.source_conditions() == [franchise, excluded]
    assert evaluate([first], FilterGroup(), context) == []


def test_order_items_sorts_unknown_values_last_and_limits() -> None:
    items = [
        _item(1, title="B", critic_rating=7.0),
        _item(2, title="A", critic_rating=None),
        _item(3, title="C", critic_rating=9.0),
        _item(4, title="D", critic_rating=7.0),
    ]
    ordered = order_items(items, CollectionOrder.CRITIC_RATING_DESC)
    assert [item.id for item in ordered] == [3, 1, 4, 2]
    ascending = order_items(items, CollectionOrder.CRITIC_RATING_ASC, limit=2)
    assert [item.id for item in ascending] == [1, 4]
    custom = order_items(items, CollectionOrder.CUSTOM, source_order=[4, 2])
    assert [item.id for item in custom] == [4, 2, 1, 3]
    assert sorted(
        item.id or 0 for item in order_items(items, CollectionOrder.RANDOM)
    ) == [1, 2, 3, 4]
    released = order_items(
        [_item(1, release_date=None, year=1980), _item(2)], CollectionOrder.RELEASE_ASC
    )
    assert [item.id for item in released] == [2, 1]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"field": "genre", "operator": "contains", "value": "a"}, "cannot use"),
        ({"field": "year", "operator": "is", "value": "abc"}, "Enter a number"),
        ({"field": "added", "operator": "in_last", "value": 0}, "whole number"),
        ({"field": "added", "operator": "before", "value": "01/02"}, "YYYY-MM-DD"),
        ({"field": "unplayed", "operator": "is", "value": "yes"}, "true or false"),
        ({"field": "genre", "operator": "is", "value": "  "}, "Enter a value"),
    ],
)
def test_field_conditions_validate_operator_and_value(
    raw: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        FieldCondition.model_validate(raw)


def test_field_conditions_normalise_values() -> None:
    assert _field(FilterField.YEAR, FilterOperator.IS, "1990").value == 1990
    assert _field(FilterField.CRITIC_RATING, FilterOperator.GTE, "7.5").value == 7.5
    assert _field(FilterField.ADDED, FilterOperator.IN_LAST, "30").value == 30
    assert (
        _field(FilterField.RELEASED, FilterOperator.AFTER, " 2020-01-02 ").value
        == "2020-01-02"
    )


def test_rules_need_a_condition_and_a_plex_order_when_smart() -> None:
    criteria = FilterGroup(
        conditions=[_field(FilterField.GENRE, FilterOperator.IS, "Action")]
    )
    with pytest.raises(ValidationError, match="at least one condition"):
        CollectionRuleWrite(criteria=FilterGroup())
    with pytest.raises(ValidationError, match="ordered by Plex"):
        CollectionRuleWrite(
            criteria=criteria, smart=True, order_type=CollectionOrder.CUSTOM
        )


def test_plex_query_uses_documented_operators_and_tag_keys() -> None:
    criteria = FilterGroup(
        conditions=[
            _field(FilterField.TITLE, FilterOperator.IS, "12 Angry Men"),
            _field(FilterField.STUDIO, FilterOperator.DOES_NOT_CONTAIN, "Fox"),
            _field(FilterField.GENRE, FilterOperator.IS, "action"),
            _field(FilterField.COUNTRY, FilterOperator.IS_NOT, "Atlantis"),
            _field(FilterField.YEAR, FilterOperator.GTE, 1990),
            _field(FilterField.USER_RATING, FilterOperator.LTE, 7),
            _field(FilterField.DURATION, FilterOperator.LT, 60),
            _field(FilterField.ADDED, FilterOperator.IN_LAST, 30),
            _field(FilterField.RELEASED, FilterOperator.BEFORE, "2000-01-01"),
            _field(FilterField.UNPLAYED, FilterOperator.IS_NOT, True),
        ]
    )
    query = compile_plex_query(
        criteria,
        media_type=MediaType.MOVIE,
        order=CollectionOrder.CRITIC_RATING_DESC,
        limit=50,
        choices={"genre": choice_keys([("12", "Action")])},
        labels={},
    )
    # The operator's "=" is encoded: Plex reads a bare "title==X" as
    # "title contains =X". ">=" and "<=" are Plex's inclusive bounds.
    assert query.split("&") == [
        "sort=rating%3Adesc",
        "limit=50",
        "title%3D=12%20Angry%20Men",
        "and=1",
        "studio%21=Fox",
        "and=1",
        "genre=12",
        "and=1",
        "country%21=-1",
        "and=1",
        "year%3E=1990",
        "and=1",
        "userRating%3C=7",
        "and=1",
        "duration%3C%3C=3600000",
        "and=1",
        "addedAt%3E%3E=-30d",
        "and=1",
        "originallyAvailableAt%3C%3C=946684800",
        "and=1",
        "unwatched=0",
    ]


def test_plex_query_works_around_what_plex_ignores_and_names_show_fields() -> None:
    criteria = FilterGroup(
        conditions=[
            _field(FilterField.DECADE, FilterOperator.IS_NOT, 1990),
            _field(FilterField.AUDIO_LANGUAGE, FilterOperator.IS_NOT, "English"),
            _field(FilterField.AUDIO_LANGUAGE, FilterOperator.IS, "english"),
            _field(FilterField.UNPLAYED, FilterOperator.IS, True),
        ]
    )
    query = compile_plex_query(
        criteria,
        media_type=MediaType.SHOW,
        order=CollectionOrder.TITLE_ASC,
        limit=None,
        choices={
            "episode.audioLanguage": choice_keys(
                [("en", "English"), ("en-US", "English"), ("sv", "Svenska")]
            )
        },
        labels={},
    )
    # Plex ignores "decade!=", lists English under two keys and tests a show's
    # audio on its episodes and its unplayed episodes as "unwatchedLeaves".
    assert query.split("&") == [
        "sort=titleSort",
        "push=1",
        "year%3C%3C=1990",
        "or=1",
        "year%3E%3E=1999",
        "pop=1",
        "and=1",
        "push=1",
        "episode.audioLanguage%21=en",
        "and=1",
        "episode.audioLanguage%21=en-US",
        "pop=1",
        "and=1",
        "episode.audioLanguage=en%2Cen-US",
        "and=1",
        "unwatchedLeaves=1",
    ]


def test_plex_query_nests_groups_and_filters_sources_by_label() -> None:
    source = SourceCondition(source=MdblistSource(identifiers=["user/list"]))
    criteria = FilterGroup(
        mode="any",
        conditions=[source],
        groups=[
            FilterGroup(
                conditions=[
                    _field(FilterField.LABEL, FilterOperator.IS, "Kids"),
                    _field(FilterField.HDR, FilterOperator.IS, True),
                ]
            ),
            FilterGroup(),
        ],
    )
    assert tag_keys(criteria, MediaType.MOVIE) == {"label"}
    query = compile_plex_query(
        criteria,
        media_type=MediaType.MOVIE,
        order=CollectionOrder.RANDOM,
        limit=None,
        choices={"label": choice_keys([("7", "overture:x"), ("8", "Kids")])},
        labels={source.key: "overture:x"},
    )
    assert query == "sort=random&label=7&or=1&push=1&label=8&and=1&hdr=1&pop=1"


def test_plex_show_queries_test_media_fields_on_episodes() -> None:
    criteria = FilterGroup(
        conditions=[
            _field(FilterField.RESOLUTION, FilterOperator.IS, "4K"),
            _field(FilterField.DOLBY_VISION, FilterOperator.IS, True),
            _field(FilterField.AGE_RATING, FilterOperator.LT, 13),
        ]
    )
    assert tag_keys(criteria, MediaType.SHOW) == {"episode.resolution"}
    query = compile_plex_query(
        criteria,
        media_type=MediaType.SHOW,
        order=CollectionOrder.TITLE_ASC,
        limit=None,
        choices={"episode.resolution": choice_keys([("4k", "4K")])},
        labels={},
    )
    assert query.split("&") == [
        "sort=titleSort",
        "episode.resolution=4k",
        "and=1",
        "episode.dovi=1",
        "and=1",
        "contentRatingAge%3C%3C=13",
    ]
    assert field_available(
        FilterField.RESOLUTION, ServerType.PLEX, MediaType.SHOW, smart=True
    )
    assert not field_available(
        FilterField.RESOLUTION, ServerType.PLEX, MediaType.SHOW, smart=False
    )
    assert not field_available(
        FilterField.EDITION, ServerType.PLEX, MediaType.SHOW, smart=True
    )


def test_fields_adapt_to_the_server_and_evaluation() -> None:
    assert field_available(
        FilterField.UNPLAYED, ServerType.PLEX, MediaType.MOVIE, smart=False
    )
    assert not field_available(
        FilterField.UNPLAYED, ServerType.JELLYFIN, MediaType.MOVIE, smart=False
    )
    assert not field_available(
        FilterField.AUDIO_LANGUAGE, ServerType.PLEX, MediaType.MOVIE, smart=False
    )
    assert field_available(
        FilterField.AUDIO_LANGUAGE, ServerType.PLEX, MediaType.MOVIE, smart=True
    )
    assert not field_available(
        FilterField.TITLE, ServerType.EMBY, MediaType.MOVIE, smart=True
    )
    assert not field_available(
        FilterField.DIRECTOR, ServerType.PLEX, MediaType.SHOW, smart=False
    )
    assert field_label(FilterField.LABEL, ServerType.JELLYFIN) == "Tag"
    assert field_label(FilterField.LABEL, ServerType.PLEX) == "Label"
    assert available_orders(ServerType.JELLYFIN, MediaType.MOVIE, smart=False) == [
        CollectionOrder.RELEASE_ASC,
        CollectionOrder.TITLE_ASC,
    ]
    plex_regular = available_orders(ServerType.PLEX, MediaType.MOVIE, smart=False)
    assert CollectionOrder.CUSTOM in plex_regular
    assert CollectionOrder.PLAYS_DESC in plex_regular
    assert CollectionOrder.CUSTOM not in available_orders(
        ServerType.PLEX, MediaType.MOVIE, smart=True
    )
    assert not dimension_available(
        SetDimension.FRANCHISE, ServerType.PLEX, MediaType.SHOW
    )


def test_sets_count_filter_rank_and_title_values() -> None:
    items = [
        _item(1, year=1977, genres=["Action", "Sci-Fi"]),
        _item(2, year=1979, genres=["Horror", "Sci-Fi"], unplayed=False),
        _item(3, year=1994, genres=["Drama"], tmdb_collection_id=10),
        _item(4, year=None, genres=[], tmdb_collection_id=10),
    ]
    decades = CollectionGeneratorBase(
        dimension=SetDimension.DECADE, title_format="{value}s"
    )
    counts = count_values(decades, items, _context())
    assert counts == Counter({"1970": 2, "1990": 1})
    values = set_values(decades, counts, {})
    assert [(value.title, value.count) for value in values] == [
        ("1970s", 2),
        ("1990s", 1),
    ]
    assert values[0].criteria.conditions == [
        _field(FilterField.DECADE, FilterOperator.IS, 1970)
    ]

    unplayed = FilterGroup(
        conditions=[_field(FilterField.UNPLAYED, FilterOperator.IS, True)]
    )
    genres = CollectionGeneratorBase(
        dimension=SetDimension.GENRE,
        criteria=unplayed,
        exclude=["drama"],
        top=1,
        title_format="Unwatched {value}",
    )
    counts = count_values(genres, items, _context())
    values = set_values(genres, counts, {})
    assert [value.title for value in values] == ["Unwatched Action"]
    assert values[0].criteria.groups == [unplayed]

    franchises = CollectionGeneratorBase(
        dimension=SetDimension.FRANCHISE,
        strip_prefix="The ",
        strip_suffix=" Collection",
        include=["the matrix collection"],
    )
    counts = count_values(franchises, items, _context())
    values = set_values(franchises, counts, {"10": "The Matrix Collection"})
    assert [(value.value, value.title) for value in values] == [("10", "Matrix")]
    assert values[0].criteria.source_conditions() == [
        SourceCondition(source=TmdbCollectionSource(collection_id=10))
    ]


def test_set_titles_need_the_value() -> None:
    with pytest.raises(ValidationError, match=r"\{value\}"):
        CollectionGeneratorBase(dimension=SetDimension.GENRE, title_format="Genre")
    with pytest.raises(ValidationError, match=r"\{value\}"):
        CollectionGeneratorBase(
            dimension=SetDimension.GENRE, title_format="{value} {title}"
        )


def test_presets_adapt_to_the_server() -> None:
    plex = {
        preset.key: preset
        for preset in available_presets(ServerType.PLEX, MediaType.MOVIE)
    }
    jellyfin = {
        preset.key for preset in available_presets(ServerType.JELLYFIN, MediaType.MOVIE)
    }
    shows = {
        preset.key for preset in available_presets(ServerType.PLEX, MediaType.SHOW)
    }
    unplayed = plex["unplayed"].collection
    assert unplayed is not None
    assert unplayed.rule.smart
    assert plex["4k"].collection is not None
    assert not plex["4k"].collection.rule.smart
    assert {"decades", "franchises", "unplayed", "short"} <= set(plex)
    assert "unplayed" not in jellyfin
    assert "decades" in jellyfin
    assert not {"franchises", "short"} & shows
    franchises = plex["franchises"].set
    assert franchises is not None
    assert franchises.generator.strip_suffix == " Collection"
