"""Zero-dependency 5-field cron expression parser and next-run calculator."""

lazy from calendar import monthrange
lazy from collections.abc import Mapping
lazy from dataclasses import dataclass
lazy from datetime import MAXYEAR, UTC, date, datetime, timedelta
lazy from functools import lru_cache
lazy from zoneinfo import ZoneInfo

MONTH_NAMES: frozendict[str, int] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
)

DOW_NAMES: frozendict[str, int] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "sun": 0,
        "mon": 1,
        "tue": 2,
        "wed": 3,
        "thu": 4,
        "fri": 5,
        "sat": 6,
    }
)


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """Parsed 5-field cron schedule representation."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    dom_restricted: bool
    dow_restricted: bool


def _parse_val(val_str: str, names: Mapping[str, int] | None) -> int:
    token = val_str.strip().lower()
    if names and token in names:
        return names[token]
    if not token.isascii() or not token.isdigit():
        raise ValueError(f"Invalid cron field token: '{val_str}'")
    return int(token)


def _parse_subpart_bounds(
    range_part: str,
    min_val: int,
    max_val: int,
    names: Mapping[str, int] | None,
    *,
    stepped: bool,
) -> tuple[int, int]:
    if range_part == "*":
        return min_val, max_val
    if "-" in range_part:
        start_str, end_str = range_part.split("-", 1)
        start = _parse_val(start_str, names)
        end = _parse_val(end_str, names)
        if start > end:
            raise ValueError(f"Invalid range '{range_part}': start > end")
    else:
        start = end = _parse_val(range_part, names)
        if stepped:
            end = max_val

    if not (min_val <= start <= end <= max_val):
        raise ValueError(f"Range {start}-{end} out of bounds [{min_val}, {max_val}]")
    return start, end


def _parse_field(
    raw: str,
    min_val: int,
    max_val: int,
    names: Mapping[str, int] | None = None,
    *,
    allow_seven_as_zero: bool = False,
) -> tuple[frozenset[int], bool]:
    values: set[int] = set()
    upper_bound = 7 if allow_seven_as_zero else max_val

    for part in raw.split(","):
        step = 1
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            step = _parse_val(step_str, None)
            if step <= 0:
                raise ValueError(f"Invalid step value: '{step_str}'")
        else:
            range_part = part

        start, end = _parse_subpart_bounds(
            range_part, min_val, upper_bound, names, stepped="/" in part
        )

        values.update(
            val % 7 if allow_seven_as_zero else val
            for val in range(start, end + 1, step)
        )
    return frozenset(values), not raw.startswith("*")


@lru_cache(maxsize=128)
def parse_cron(expression: str) -> CronSchedule:
    """Parse and validate a standard five-field crontab expression."""
    parts = expression.split()
    if not parts:
        raise ValueError("cron_expression is required")

    if len(parts) != 5:
        raise ValueError("cron_expression must be a valid 5-field crontab expression")

    try:
        minutes, _ = _parse_field(parts[0], 0, 59)
        hours, _ = _parse_field(parts[1], 0, 23)
        dom, dom_restricted = _parse_field(parts[2], 1, 31)
        months, _ = _parse_field(parts[3], 1, 12, MONTH_NAMES)
        dow, dow_restricted = _parse_field(
            parts[4], 0, 6, DOW_NAMES, allow_seven_as_zero=True
        )
        # A leap year contains every possible month/day combination.
        if not (dom_restricted and dow_restricted) and not any(
            day <= monthrange(2000, month)[1] for month in months for day in dom
        ):
            raise ValueError("Cron expression has no matching calendar date")
    except ValueError as exc:
        raise ValueError(
            "cron_expression must be a valid 5-field crontab expression"
        ) from exc

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        days_of_month=dom,
        months=months,
        days_of_week=dow,
        dom_restricted=dom_restricted,
        dow_restricted=dow_restricted,
    )


def validate_cron_expression(expression: str) -> str:
    """Normalize and validate a five-field crontab expression."""
    normalized = " ".join(expression.split())
    parse_cron(normalized)
    return normalized


def next_run_after(
    expression: str,
    after: datetime,
    *,
    tz: ZoneInfo | None = None,
) -> datetime:
    """Find the next instant, skipping DST gaps and including both DST folds."""
    schedule = parse_cron(expression)
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    target_tz = tz or after.tzinfo
    after_utc = after.astimezone(UTC)
    day = after.astimezone(target_tz).replace(
        hour=0, minute=0, second=0, microsecond=0, fold=0
    )
    hours = sorted(schedule.hours)
    minutes = sorted(schedule.minutes)

    # The Gregorian calendar repeats every 400 years.
    last_year = min(day.year + 400, MAXYEAR)
    while day.year <= last_year:
        cron_dow = (day.weekday() + 1) % 7
        if schedule.dom_restricted and schedule.dow_restricted:
            day_matches = (day.day in schedule.days_of_month) or (
                cron_dow in schedule.days_of_week
            )
        else:
            day_matches = (day.day in schedule.days_of_month) and (
                cron_dow in schedule.days_of_week
            )
        if day.month in schedule.months and day_matches:
            candidates = (
                day.replace(hour=hour, minute=minute, fold=fold).astimezone(UTC)
                for hour in hours
                for minute in minutes
                for fold in (0, 1)
            )
            # Round-tripping rejects nonexistent wall times and normalizes folds.
            valid = (
                instant
                for instant in candidates
                if instant > after_utc
                and (local := instant.astimezone(target_tz)).date() == day.date()
                and local.hour in schedule.hours
                and local.minute in schedule.minutes
            )
            if (next_utc := min(valid, default=None)) is not None:
                return next_utc.astimezone(target_tz)
        if day.date() == date.max:
            break
        day += timedelta(days=1)

    raise ValueError(f"No matching execution time for '{expression}'")
