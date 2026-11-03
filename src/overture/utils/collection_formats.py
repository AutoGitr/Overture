"""Restricted templates and seasonal date windows shared by collection workflows."""

lazy import re
lazy from datetime import date
lazy from string import Formatter
lazy from typing import Annotated

lazy from pydantic import AfterValidator, Field

MAX_COLLECTION_SUMMARY_LENGTH = 10_000

_SUMMARY_FIELDS = frozenset(
    {"title", "group", "start_date", "end_date", "summary", "source_summary"}
)
_DAYS_IN_MONTH = (0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def literal_template(value: str) -> str:
    """Quote literal metadata so braces are not interpreted as template fields."""
    return value.replace("{", "{{").replace("}", "}}")


def validate_sort_title_format(value: str) -> str:
    """Allow literal text and named fields without attribute access or formats."""
    for _, name, spec, conversion in Formatter().parse(value):
        if name is not None and (name not in {"title", "group"} or spec or conversion):
            raise ValueError("Use only {title} and {group} in sort-title templates")
    return value


# Escaped literal braces can double expression length without growing the output.
type SortTitleFormat = Annotated[
    str, Field(max_length=400), AfterValidator(validate_sort_title_format)
]


def format_sort_title(template: str, *, title: str, group: str | None) -> str:
    """Render a validated template without silently truncating server metadata."""
    result = validate_sort_title_format(template).format(title=title, group=group or "")
    if len(result) > 200:
        raise ValueError("The formatted sort title must be at most 200 characters")
    return result


#: A label or Radarr/Sonarr tag given to a collection's members.
type MemberTagFormat = Annotated[
    str, Field(min_length=1, max_length=200), AfterValidator(validate_sort_title_format)
]


def format_member_tag(template: str, *, title: str, group: str | None) -> str:
    """Render a validated member tag template."""
    result = template.format(title=title, group=group or "").strip()
    if not result:
        raise ValueError("The member tag renders empty")
    return result[:200]


def validate_set_title_format(value: str) -> str:
    """Require the set's value, which keeps each collection's title distinct."""
    names = {
        (name, spec, conversion)
        for _, name, spec, conversion in Formatter().parse(value)
        if name is not None
    }
    if names != {("value", "", None)}:
        raise ValueError("Use {value} once or more, and no other fields")
    return value


type SetTitleFormat = Annotated[
    str, Field(max_length=200), AfterValidator(validate_set_title_format)
]


def format_set_title(template: str, value: str) -> str:
    """Render a validated set title template."""
    return validate_set_title_format(template).format(value=value).strip()


def validate_summary_format(value: str) -> str:
    """Allow literal text and summary fields without attribute access or formats."""
    for _, name, spec, conversion in Formatter().parse(value):
        if name is not None and (name not in _SUMMARY_FIELDS or spec or conversion):
            raise ValueError(
                "Use only {title}, {group}, {start_date}, {end_date}, {summary} "
                "and {source_summary} in summary templates"
            )
    return value


type SummaryFormat = Annotated[
    str,
    Field(max_length=MAX_COLLECTION_SUMMARY_LENGTH * 2),
    AfterValidator(validate_summary_format),
]


def format_summary(
    template: str,
    *,
    title: str,
    group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    summary: str | None = None,
    source_summary: str | None = None,
) -> str:
    """Render a validated summary template."""
    result = validate_summary_format(template).format(
        title=title,
        group=group or "",
        start_date=start_date or "",
        end_date=end_date or "",
        summary=summary or "",
        source_summary=source_summary or "",
    )
    if len(result) > MAX_COLLECTION_SUMMARY_LENGTH:
        raise ValueError(
            "The formatted summary must be at most "
            f"{MAX_COLLECTION_SUMMARY_LENGTH} characters"
        )
    return result


def validate_seasonal_mmdd(value: str) -> str:
    """Validate an ``MM-DD`` calendar date."""
    value = value.strip()
    if not re.fullmatch(r"[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use MM-DD format for seasonal dates (for example 12-01)")
    month, day = int(value[:2]), int(value[3:])
    if month < 1 or month > 12 or day < 1 or day > _DAYS_IN_MONTH[month]:
        raise ValueError(f"{value!r} is not a valid calendar date")
    return value


type SeasonalDate = Annotated[
    str, Field(min_length=5, max_length=5), AfterValidator(validate_seasonal_mmdd)
]


def is_within_active_window(
    start_mmdd: str | None,
    end_mmdd: str | None,
    today: date,
) -> bool:
    """Return whether *today* falls within the inclusive ``[start, end]`` window.

    Handles year-wrapping ranges such as ``12-31`` through ``01-04``.
    """
    if not start_mmdd or not end_mmdd:
        return True
    start = validate_seasonal_mmdd(start_mmdd)
    end = validate_seasonal_mmdd(end_mmdd)
    current = f"{today.month:02d}-{today.day:02d}"
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def strip_affixes(title: str, *, prefix: str, suffix: str) -> str:
    """Strip configured prefix and suffix from a TMDB collection title."""
    cleaned = title.strip()
    if prefix and cleaned.casefold().startswith(prefix.casefold()):
        cleaned = cleaned[len(prefix) :].strip()
    if suffix and cleaned.casefold().endswith(suffix.casefold()):
        cleaned = cleaned[: -len(suffix)].strip()
    return cleaned or title.strip()
