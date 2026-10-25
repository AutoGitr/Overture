"""Restricted sort-title templates shared by collection workflows."""

lazy from string import Formatter
lazy from typing import Annotated

lazy from pydantic import AfterValidator, Field


def validate_sort_title_format(value: str) -> str:
    """Allow literal text and named fields without attribute access or formats."""
    for _, name, spec, conversion in Formatter().parse(value):
        if name is not None and (name not in {"title", "group"} or spec or conversion):
            raise ValueError("Use only {title} and {group} in sort-title templates")
    return value


type SortTitleFormat = Annotated[
    str, Field(max_length=200), AfterValidator(validate_sort_title_format)
]


def format_sort_title(template: str, *, title: str, group: str | None) -> str:
    """Render a validated template without silently truncating server metadata."""
    result = validate_sort_title_format(template).format(title=title, group=group or "")
    if len(result) > 200:
        raise ValueError("The formatted sort title must be at most 200 characters")
    return result
