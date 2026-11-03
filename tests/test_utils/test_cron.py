"""Unit tests for the zero-dependency 5-field cron parser and evaluator."""

lazy from datetime import UTC, datetime
lazy from zoneinfo import ZoneInfo

lazy import pytest

lazy from overture.utils.cron import (
    next_run_after,
    parse_cron,
    validate_cron_expression,
)


def test_validate_cron_expression_valid() -> None:
    assert validate_cron_expression("0 3 * * *") == "0 3 * * *"
    assert validate_cron_expression("  0  *  *  *  *  ") == "0 * * * *"
    assert validate_cron_expression("*/15 * * * *") == "*/15 * * * *"
    assert validate_cron_expression("0 */6 * * 1-5") == "0 */6 * * 1-5"
    assert validate_cron_expression("0 0 1 1 *") == "0 0 1 1 *"
    assert validate_cron_expression("0 0 * * SUN") == "0 0 * * SUN"
    assert validate_cron_expression("0 0 * * 7") == "0 0 * * 7"
    assert validate_cron_expression("0 0 * * 5-7") == "0 0 * * 5-7"
    assert validate_cron_expression("0 0 * JAN-MAR MON-FRI") == "0 0 * JAN-MAR MON-FRI"


def test_validate_cron_expression_invalid() -> None:
    with pytest.raises(ValueError, match="cron_expression is required"):
        validate_cron_expression("")

    with pytest.raises(ValueError, match="cron_expression is required"):
        validate_cron_expression("   ")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * * * * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("60 * * * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* 24 * * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * 32 * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * 0 * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * * 13 *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * * 0 *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("* * * * 8")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("*/0 * * * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("5-2 * * * *")

    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression("invalid cron format here now")


def test_parse_cron_details() -> None:
    schedule = parse_cron("15,30 2-4 1,15 * 1-5")
    assert schedule.minutes == frozenset({15, 30})
    assert schedule.hours == frozenset({2, 3, 4})
    assert schedule.days_of_month == frozenset({1, 15})
    assert schedule.months == frozenset(range(1, 13))
    assert schedule.days_of_week == frozenset({1, 2, 3, 4, 5})
    assert schedule.dom_restricted is True
    assert schedule.dow_restricted is True


def test_next_run_after_basic() -> None:
    base = datetime(2026, 10, 3, 16, 15, 30, tzinfo=UTC)

    # Hourly: next run is 17:00
    assert next_run_after("0 * * * *", base) == datetime(
        2026, 10, 3, 17, 0, 0, tzinfo=UTC
    )

    # Next 15-minute mark: 16:30
    assert next_run_after("*/15 * * * *", base) == datetime(
        2026, 10, 3, 16, 30, 0, tzinfo=UTC
    )

    # Daily at 3 AM: next day 03:00
    assert next_run_after("0 3 * * *", base) == datetime(
        2026, 10, 4, 3, 0, 0, tzinfo=UTC
    )

    # Daily at 20:00 (later today)
    assert next_run_after("0 20 * * *", base) == datetime(
        2026, 10, 3, 20, 0, 0, tzinfo=UTC
    )


def test_next_run_after_weekday() -> None:
    # 2026-10-03 is Saturday (cron DOW = 6)
    base = datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)

    # Next Sunday (DOW 0) at midnight
    assert next_run_after("0 0 * * 0", base) == datetime(
        2026, 10, 4, 0, 0, 0, tzinfo=UTC
    )
    # Sunday with 7
    assert next_run_after("0 0 * * 7", base) == datetime(
        2026, 10, 4, 0, 0, 0, tzinfo=UTC
    )
    # Sunday with SUN
    assert next_run_after("0 0 * * SUN", base) == datetime(
        2026, 10, 4, 0, 0, 0, tzinfo=UTC
    )

    # Next Monday (DOW 1) at 09:00
    assert next_run_after("0 9 * * 1", base) == datetime(
        2026, 10, 5, 9, 0, 0, tzinfo=UTC
    )


def test_next_run_after_dom_and_dow_union() -> None:
    # Standard POSIX / Vixie cron behavior: when BOTH DOM and DOW are specified,
    # the job runs if EITHER DOM or DOW matches (OR logic).
    # 2026-10-03 is Saturday.
    base = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
    # 15th of the month OR Sunday
    # Next Sunday is 2026-10-04 (matches DOW). 15th is 2026-10-15 (matches DOM).
    # First matching date should be 2026-10-04!
    assert next_run_after("0 0 15 * 0", base) == datetime(
        2026, 10, 4, 0, 0, 0, tzinfo=UTC
    )


def test_next_run_after_month_and_leap_year() -> None:
    # 2028 is a leap year (Feb 29 exists)
    base = datetime(2028, 2, 28, 12, 0, 0, tzinfo=UTC)
    assert next_run_after("0 0 29 2 *", base) == datetime(
        2028, 2, 29, 0, 0, 0, tzinfo=UTC
    )

    # Year rollover: next January 1st
    base2 = datetime(2026, 12, 15, 0, 0, 0, tzinfo=UTC)
    assert next_run_after("0 0 1 1 *", base2) == datetime(
        2027, 1, 1, 0, 0, 0, tzinfo=UTC
    )


def test_next_run_after_timezone() -> None:
    tz = ZoneInfo("Europe/Stockholm")
    base = datetime(2026, 10, 3, 14, 0, 0, tzinfo=UTC)  # 16:00 in Stockholm
    result = next_run_after("0 4 * * *", base, tz=tz)
    assert result.tzinfo == tz
    assert result == datetime(2026, 10, 4, 4, 0, 0, tzinfo=tz)


@pytest.mark.parametrize("expression", ["0 0 31 2 *", "0 0 31 4 *", "0 0 30 2 */2"])
def test_impossible_calendar_dates_are_rejected(expression: str) -> None:
    with pytest.raises(ValueError, match="valid 5-field crontab"):
        validate_cron_expression(expression)


def test_scalar_steps_and_wildcard_days() -> None:
    assert parse_cron("5/15 * * * *").minutes == frozenset({5, 20, 35, 50})
    assert next_run_after(
        "0 0 */2 * MON", datetime(2026, 10, 3, tzinfo=UTC)
    ) == datetime(2026, 10, 5, tzinfo=UTC)
    # An impossible month-day is still valid when the weekday can match.
    assert next_run_after("0 0 31 2 MON", datetime(2026, 2, 1, tzinfo=UTC)) == datetime(
        2026, 2, 2, tzinfo=UTC
    )


def test_leap_day_can_be_more_than_five_years_away() -> None:
    assert next_run_after("0 0 29 2 *", datetime(2096, 3, 1, tzinfo=UTC)) == datetime(
        2104, 2, 29, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("expression", "after", "expected"),
    [
        ("30 2 * * *", "2026-03-29T00:00:00+00:00", "2026-03-30T00:30:00+00:00"),
        ("0 4 * * *", "2026-03-28T04:00:00+00:00", "2026-03-29T02:00:00+00:00"),
        ("30 2 * * *", "2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00+00:00"),
        ("30 2 * * *", "2026-10-25T01:30:00+00:00", "2026-10-26T01:30:00+00:00"),
        ("* * * * *", "2026-10-25T00:59:59+00:00", "2026-10-25T01:00:00+00:00"),
    ],
)
def test_dst_gaps_and_folds(expression: str, after: str, expected: str) -> None:
    result = next_run_after(
        expression, datetime.fromisoformat(after), tz=ZoneInfo("Europe/Stockholm")
    )
    assert result.astimezone(UTC) == datetime.fromisoformat(expected)
