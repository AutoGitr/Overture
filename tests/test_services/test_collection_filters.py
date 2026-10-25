"""Tests for composable collection filters and Plex smart filter compiler."""

lazy from datetime import UTC, datetime, timedelta

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import (
    FilterField,
    FilterOperator,
    MediaType,
    SmartSortOrder,
)
lazy from overture.schemas.collections import (
    FilterCondition,
    FilterGroup,
    SmartCollectionConfig,
)
lazy from overture.services.collections.filters import (
    compile_plex_smart_filter,
    evaluate_filter_group,
)


def _make_item(**kwargs: object) -> MediaItem:
    defaults: dict[str, object] = {
        "id": 1,
        "server_id": "item1",
        "library_id": "lib1",
        "media_type": MediaType.MOVIE,
        "title": "Star Wars: A New Hope",
        "year": 1977,
        "release_date": "1977-05-25",
        "rating": 8.6,
        "duration_minutes": 121,
        "studio": "Lucasfilm",
        "director": "George Lucas",
        "content_rating": "PG",
        "resolution": "4K",
        "audio_language": "en",
        "genres": ["Action", "Adventure", "Sci-Fi"],
        "actors": ["Mark Hamill", "Harrison Ford", "Carrie Fisher"],
        "writers": ["George Lucas"],
        "producers": ["Gary Kurtz"],
        "countries": ["USA"],
        "labels": ["Sci-Fi Classic"],
        "tags": ["space-opera"],
        "unplayed": True,
        "in_progress": False,
        "server_added_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return MediaItem(**defaults)


def test_text_matching_operators() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    item = _make_item()

    # IS & IS_NOT
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.TITLE,
                    operator=FilterOperator.IS,
                    value="star wars: a new hope",
                )
            ]
        ),
        now=now,
    ) == [item]
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.TITLE,
                    operator=FilterOperator.IS_NOT,
                    value="Star Trek",
                )
            ]
        ),
        now=now,
    ) == [item]

    # CONTAINS & DOES_NOT_CONTAIN
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.STUDIO,
                    operator=FilterOperator.CONTAINS,
                    value="lucas",
                )
            ]
        ),
        now=now,
    ) == [item]
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.STUDIO,
                    operator=FilterOperator.DOES_NOT_CONTAIN,
                    value="disney",
                )
            ]
        ),
        now=now,
    ) == [item]

    # STARTS_WITH
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.TITLE,
                    operator=FilterOperator.STARTS_WITH,
                    value="star",
                )
            ]
        ),
        now=now,
    ) == [item]

    # Other text fields: director, content_rating, resolution, audio_language
    for field, val in [
        (FilterField.DIRECTOR, "George Lucas"),
        (FilterField.CONTENT_RATING, "PG"),
        (FilterField.RESOLUTION, "4K"),
        (FilterField.AUDIO_LANGUAGE, "en"),
    ]:
        assert evaluate_filter_group(
            [item],
            FilterGroup(
                conditions=[
                    FilterCondition(
                        field=field,
                        operator=FilterOperator.IS,
                        value=val,
                    )
                ]
            ),
            now=now,
        ) == [item]


def test_list_matching_operators() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    item = _make_item()

    # GENRE contains / is
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.GENRE,
                    operator=FilterOperator.IS,
                    value="sci-fi",
                )
            ]
        ),
        now=now,
    ) == [item]
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.GENRE,
                    operator=FilterOperator.IS_NOT,
                    value="Horror",
                )
            ]
        ),
        now=now,
    ) == [item]
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.GENRE,
                    operator=FilterOperator.DOES_NOT_CONTAIN,
                    value="Horror",
                )
            ]
        ),
        now=now,
    ) == [item]

    # ACTOR, WRITER, PRODUCER, COUNTRY, LABEL, TAG
    for field, val in [
        (FilterField.ACTOR, "Harrison Ford"),
        (FilterField.WRITER, "George Lucas"),
        (FilterField.PRODUCER, "Gary Kurtz"),
        (FilterField.COUNTRY, "USA"),
        (FilterField.LABEL, "Sci-Fi Classic"),
        (FilterField.TAG, "space-opera"),
    ]:
        assert evaluate_filter_group(
            [item],
            FilterGroup(
                conditions=[
                    FilterCondition(
                        field=field,
                        operator=FilterOperator.CONTAINS,
                        value=val,
                    )
                ]
            ),
            now=now,
        ) == [item]


def test_numeric_and_boolean_matching() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    item = _make_item(year=1980, rating=8.7, duration_minutes=124)

    # YEAR & DECADE
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.YEAR,
                    operator=FilterOperator.GTE,
                    value=1970,
                ),
                FilterCondition(
                    field=FilterField.DECADE,
                    operator=FilterOperator.IS,
                    value=1980,
                ),
            ]
        ),
        now=now,
    ) == [item]

    # DECADE with None year
    item_no_year = _make_item(year=None)
    assert (
        evaluate_filter_group(
            [item_no_year],
            FilterGroup(
                conditions=[
                    FilterCondition(
                        field=FilterField.DECADE,
                        operator=FilterOperator.IS,
                        value=1980,
                    )
                ]
            ),
            now=now,
        )
        == []
    )
    assert evaluate_filter_group(
        [item_no_year],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.DECADE,
                    operator=FilterOperator.IS_NOT,
                    value=1980,
                )
            ]
        ),
        now=now,
    ) == [item_no_year]

    # RATING & DURATION
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.RATING,
                    operator=FilterOperator.GTE,
                    value=8.0,
                ),
                FilterCondition(
                    field=FilterField.DURATION_MINUTES,
                    operator=FilterOperator.LTE,
                    value=150,
                ),
            ]
        ),
        now=now,
    ) == [item]

    # UNPLAYED & IN_PROGRESS
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.UNPLAYED,
                    operator=FilterOperator.IS,
                    value=True,
                ),
                FilterCondition(
                    field=FilterField.IN_PROGRESS,
                    operator=FilterOperator.IS,
                    value=False,
                ),
            ]
        ),
        now=now,
    ) == [item]
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.UNPLAYED,
                    operator=FilterOperator.IS_NOT,
                    value=False,
                )
            ]
        ),
        now=now,
    ) == [item]


def test_date_matching() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    item = _make_item(
        server_added_at=now - timedelta(days=10),
        release_date="2026-10-15",
    )

    # ADDED_WITHIN_DAYS
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.ADDED_WITHIN_DAYS,
                    operator=FilterOperator.LTE,
                    value=15,
                )
            ]
        ),
        now=now,
    ) == [item]
    assert (
        evaluate_filter_group(
            [item],
            FilterGroup(
                conditions=[
                    FilterCondition(
                        field=FilterField.ADDED_WITHIN_DAYS,
                        operator=FilterOperator.LTE,
                        value=5,
                    )
                ]
            ),
            now=now,
        )
        == []
    )

    # RELEASED_WITHIN_DAYS
    assert evaluate_filter_group(
        [item],
        FilterGroup(
            conditions=[
                FilterCondition(
                    field=FilterField.RELEASED_WITHIN_DAYS,
                    operator=FilterOperator.LTE,
                    value=20,
                )
            ]
        ),
        now=now,
    ) == [item]

    # Invalid release date or far in future
    invalid_item = _make_item(release_date="not-a-date")
    assert (
        evaluate_filter_group(
            [invalid_item],
            FilterGroup(
                conditions=[
                    FilterCondition(
                        field=FilterField.RELEASED_WITHIN_DAYS,
                        operator=FilterOperator.LTE,
                        value=30,
                    )
                ]
            ),
            now=now,
        )
        == []
    )


def test_nested_filter_groups_and_empty() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    item1 = _make_item(title="Alien", genres=["Sci-Fi", "Horror"])
    item2 = _make_item(title="Blade Runner", genres=["Sci-Fi", "Thriller"])

    # Empty group returns []
    assert evaluate_filter_group([item1, item2], FilterGroup()) == []

    # Filter with any matching mode
    group_any = FilterGroup(
        mode="any",
        conditions=[
            FilterCondition(
                field=FilterField.TITLE,
                operator=FilterOperator.IS,
                value="Alien",
            ),
            FilterCondition(
                field=FilterField.TITLE,
                operator=FilterOperator.IS,
                value="Blade Runner",
            ),
        ],
    )
    assert evaluate_filter_group([item1, item2], group_any, now=now) == [item1, item2]

    # Nested groups: (Sci-Fi AND (Horror OR Thriller))
    nested = FilterGroup(
        mode="all",
        conditions=[
            FilterCondition(
                field=FilterField.GENRE,
                operator=FilterOperator.IS,
                value="Sci-Fi",
            )
        ],
        groups=[
            FilterGroup(
                mode="any",
                conditions=[
                    FilterCondition(
                        field=FilterField.GENRE,
                        operator=FilterOperator.IS,
                        value="Horror",
                    ),
                    FilterCondition(
                        field=FilterField.GENRE,
                        operator=FilterOperator.IS,
                        value="Thriller",
                    ),
                ],
            )
        ],
    )
    assert evaluate_filter_group([item1, item2], nested, now=now) == [item1, item2]


def test_compile_plex_smart_filter() -> None:
    # Basic config with sort and limit
    config = SmartCollectionConfig(
        sort_by=SmartSortOrder.RELEASE_DESC,
        limit=50,
        filter_group=FilterGroup(
            mode="all",
            conditions=[
                FilterCondition(
                    field=FilterField.GENRE,
                    operator=FilterOperator.IS,
                    value="Action",
                ),
                FilterCondition(
                    field=FilterField.UNPLAYED,
                    operator=FilterOperator.IS,
                    value=True,
                ),
                FilterCondition(
                    field=FilterField.IN_PROGRESS,
                    operator=FilterOperator.IS_NOT,
                    value=True,
                ),
                FilterCondition(
                    field=FilterField.ADDED_WITHIN_DAYS,
                    operator=FilterOperator.LTE,
                    value=30,
                ),
                FilterCondition(
                    field=FilterField.DECADE,
                    operator=FilterOperator.IS_NOT,
                    value=1990,
                ),
                FilterCondition(
                    field=FilterField.DURATION_MINUTES,
                    operator=FilterOperator.GTE,
                    value=90,
                ),
                FilterCondition(
                    field=FilterField.DURATION_MINUTES,
                    operator=FilterOperator.LTE,
                    value=180,
                ),
            ],
        ),
    )
    compiled = compile_plex_smart_filter(config)
    assert "sort=originallyAvailableAt:desc" in compiled
    assert "limit=50" in compiled
    assert "genre==Action" in compiled
    assert "unwatched=1" in compiled
    assert "inProgress=0" in compiled
    assert "addedAt>>=-30d" in compiled
    assert "decade!=1990" in compiled
    assert "duration>>=5400000" in compiled
    assert "duration<<=10800000" in compiled

    # Managed label injected into empty group
    empty_config = SmartCollectionConfig(
        sort_by=SmartSortOrder.TITLE_ASC,
        filter_group=FilterGroup(),
    )
    compiled_label = compile_plex_smart_filter(
        empty_config, managed_label="Overture Managed"
    )
    assert "label==Overture+Managed" in compiled_label

    # Managed label with mode=any wraps original in sub-group
    any_config = SmartCollectionConfig(
        sort_by=SmartSortOrder.TITLE_ASC,
        filter_group=FilterGroup(
            mode="any",
            conditions=[
                FilterCondition(
                    field=FilterField.GENRE,
                    operator=FilterOperator.IS,
                    value="Drama",
                ),
                FilterCondition(
                    field=FilterField.GENRE,
                    operator=FilterOperator.IS,
                    value="Comedy",
                ),
            ],
        ),
    )
    compiled_any = compile_plex_smart_filter(any_config, managed_label="Managed")
    assert "label==Managed" in compiled_any
    assert "or=1" in compiled_any


def test_filters_edge_cases_and_helpers() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    item = _make_item()

    # Text filter unsupported operator returns False
    cond_text_gte = FilterCondition(
        field=FilterField.TITLE, operator=FilterOperator.GTE, value="world"
    )
    assert evaluate_filter_group([item], FilterGroup(conditions=[cond_text_gte])) == []

    # Number filter unsupported operator returns False & IS_NOT matches
    cond_num_contains = FilterCondition(
        field=FilterField.YEAR, operator=FilterOperator.CONTAINS, value=1977
    )
    assert (
        evaluate_filter_group([item], FilterGroup(conditions=[cond_num_contains])) == []
    )
    cond_num_is_not = FilterCondition(
        field=FilterField.YEAR, operator=FilterOperator.IS_NOT, value=2000
    )
    assert evaluate_filter_group([item], FilterGroup(conditions=[cond_num_is_not])) == [
        item
    ]

    # Bool conversions (1, 0, yes, no)
    cond_bool_int = FilterCondition(
        field=FilterField.UNPLAYED, operator=FilterOperator.IS, value=1
    )
    assert evaluate_filter_group([item], FilterGroup(conditions=[cond_bool_int])) == [
        item
    ]
    cond_bool_str = FilterCondition(
        field=FilterField.UNPLAYED, operator=FilterOperator.IS, value="yes"
    )
    assert evaluate_filter_group([item], FilterGroup(conditions=[cond_bool_str])) == [
        item
    ]
    cond_bool_zero = FilterCondition(
        field=FilterField.IN_PROGRESS, operator=FilterOperator.IS, value=0
    )
    assert evaluate_filter_group([item], FilterGroup(conditions=[cond_bool_zero])) == [
        item
    ]
    cond_bool_no = FilterCondition(
        field=FilterField.IN_PROGRESS, operator=FilterOperator.IS, value="no"
    )
    assert evaluate_filter_group([item], FilterGroup(conditions=[cond_bool_no])) == [
        item
    ]

    # Added within days when server_added_at is None returns False
    item_no_added = _make_item(server_added_at=None)
    cond_added = FilterCondition(
        field=FilterField.ADDED_WITHIN_DAYS, operator=FilterOperator.LTE, value=30
    )
    assert (
        evaluate_filter_group(
            [item_no_added], FilterGroup(conditions=[cond_added]), now=now
        )
        == []
    )

    # Empty sub-groups skipped
    empty_sub = FilterGroup(
        mode="all",
        conditions=[
            FilterCondition(
                field=FilterField.TITLE,
                operator=FilterOperator.IS,
                value="Star Wars: A New Hope",
            )
        ],
        groups=[FilterGroup()],
    )
    assert evaluate_filter_group([item], empty_sub, now=now) == [item]

    # Smart filter with label already present in conditions
    label_cond = FilterCondition(
        field=FilterField.LABEL,
        operator=FilterOperator.IS,
        value="Managed",
    )
    already_has_label = SmartCollectionConfig(
        filter_group=FilterGroup(mode="all", conditions=[label_cond])
    )
    compiled_existing = compile_plex_smart_filter(
        already_has_label, managed_label="Managed"
    )
    assert "label==Managed" in compiled_existing

    # Smart filter without group pairs
    no_pairs = SmartCollectionConfig(filter_group=FilterGroup())
    assert compile_plex_smart_filter(no_pairs) == "sort=originallyAvailableAt:desc"
