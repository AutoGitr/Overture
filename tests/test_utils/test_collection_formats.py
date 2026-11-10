"""Tests for collection formatting templates and seasonal date window calculations."""

lazy from datetime import date

lazy import pytest

lazy from overture.utils.collection_formats import (
    format_arr_tag,
    format_sort_title,
    format_summary,
    is_within_active_window,
    sortable,
    strip_affixes,
    validate_seasonal_mmdd,
    validate_sort_title_format,
    validate_summary_format,
)


def test_sort_title_formatting() -> None:
    # Valid templates
    assert validate_sort_title_format("{title}") == "{title}"
    assert validate_sort_title_format("{group} - {title}") == "{group} - {title}"
    assert format_sort_title("+1_{title}", title="Alien", group=None) == "+1_Alien"
    assert (
        format_sort_title("{group}: {title}", title="Part 1", group="Saga")
        == "Saga: Part 1"
    )

    # Invalid templates with disallowed tokens or formatting specs
    with pytest.raises(ValueError, match="sort-title templates"):
        validate_sort_title_format("{invalid_field}")
    with pytest.raises(ValueError, match="sort-title templates"):
        validate_sort_title_format("{title:02d}")

    # Exceeding 200 characters raises
    with pytest.raises(ValueError, match="at most 200 characters"):
        format_sort_title("{title}_{group}", title="A" * 150, group="B" * 60)


def test_summary_formatting() -> None:
    # Valid templates
    assert validate_summary_format("{title} overview") == "{title} overview"
    assert (
        format_summary(
            "{title} ({start_date} - {end_date}): {summary}",
            title="Christmas",
            start_date="12-01",
            end_date="12-31",
            summary="Holiday movies",
        )
        == "Christmas (12-01 - 12-31): Holiday movies"
    )

    # Invalid templates with disallowed tokens or specs
    with pytest.raises(ValueError, match="summary templates"):
        validate_summary_format("{disallowed}")
    with pytest.raises(ValueError, match="summary templates"):
        validate_summary_format("{title:03d}")

    # Exceeding 10000 characters raises
    with pytest.raises(ValueError, match="at most 10000 characters"):
        format_summary("{title}", title="X" * 10001)


def test_seasonal_dates_and_windows() -> None:
    # Valid MM-DD
    assert validate_seasonal_mmdd("12-25") == "12-25"
    assert validate_seasonal_mmdd("02-29") == "02-29"

    # Invalid formats
    with pytest.raises(ValueError, match="Use MM-DD format"):
        validate_seasonal_mmdd("invalid")
    with pytest.raises(ValueError, match="Use MM-DD format"):
        validate_seasonal_mmdd("12/25")

    # Invalid calendar dates
    with pytest.raises(ValueError, match="not a valid calendar date"):
        validate_seasonal_mmdd("13-01")
    with pytest.raises(ValueError, match="not a valid calendar date"):
        validate_seasonal_mmdd("02-30")
    with pytest.raises(ValueError, match="not a valid calendar date"):
        validate_seasonal_mmdd("04-31")

    # Active window checks
    # None bounds are always active
    assert is_within_active_window(None, None, date(2026, 6, 15)) is True
    assert is_within_active_window("12-01", None, date(2026, 6, 15)) is True

    # Same-year range [10-01, 10-31]
    assert is_within_active_window("10-01", "10-31", date(2026, 10, 15)) is True
    assert is_within_active_window("10-01", "10-31", date(2026, 11, 1)) is False

    # Year-wrapping range [12-01, 01-15]
    assert is_within_active_window("12-01", "01-15", date(2026, 12, 25)) is True
    assert is_within_active_window("12-01", "01-15", date(2026, 1, 10)) is True
    assert is_within_active_window("12-01", "01-15", date(2026, 6, 1)) is False


def test_strip_affixes() -> None:
    # Prefix and suffix stripping
    assert (
        strip_affixes("The Avengers Collection", prefix="The ", suffix=" Collection")
        == "Avengers"
    )
    # Case-insensitive stripping
    assert (
        strip_affixes("the star wars collection", prefix="The ", suffix=" Collection")
        == "star wars"
    )
    # Only prefix
    assert (
        strip_affixes("A Christmas Story", prefix="A ", suffix="") == "Christmas Story"
    )
    # Only suffix
    assert strip_affixes("Toy Story Series", prefix="", suffix=" Series") == "Toy Story"
    # No matching affixes
    assert (
        strip_affixes("The Godfather", prefix="An ", suffix=" Trilogy")
        == "The Godfather"
    )
    # Empty title or stripped to empty falls back to original trimmed title
    assert strip_affixes("   The   ", prefix="The", suffix="") == "The"


def test_arr_tags_are_rendered_as_radarr_accepts_and_never_overtures_own() -> None:
    assert format_arr_tag("{group} {title}", title="Amélie", group="Saga") == (
        "saga-amelie"
    )
    with pytest.raises(ValueError, match="no letters or digits"):
        format_arr_tag("{title}", title="!!!", group=None)
    with pytest.raises(ValueError, match="titles it adds"):
        format_arr_tag("{title}", title="Overture", group=None)


@pytest.mark.parametrize(
    ("title", "sorted_as"),
    [
        ("The Matrix Collection", "Matrix Collection"),
        ("A Quiet Place Collection", "Quiet Place Collection"),
        ("An American Tail", "American Tail"),
        ("the lord of the rings", "lord of the rings"),
        ("Anaconda", "Anaconda"),
        ("Theodore Rex", "Theodore Rex"),
        ("The", "The"),
        ("The The", "The"),
        ("  The  Godfather ", "Godfather"),
    ],
)
def test_sort_titles_drop_a_leading_article_as_plex_does(
    title: str, sorted_as: str
) -> None:
    assert sortable(title) == sorted_as


def test_sort_title_templates_sort_title_and_group_without_articles() -> None:
    assert (
        format_sort_title("{group} {title}", title="The Matrix", group="The Sagas")
        == "Sagas Matrix"
    )
    # A separator's sort title is its group's, which sorts before every member.
    separator = format_sort_title("{group} {title}", title="", group="The Sagas")
    assert separator.strip() == "Sagas"
    members = [
        format_sort_title("{group} {title}", title=title, group="The Sagas")
        for title in ("Alien", "The Abyss", "A Bug's Life")
    ]
    assert min([*members, separator.strip()]) == "Sagas"
