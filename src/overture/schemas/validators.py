"""Shared schema field types."""

lazy from typing import Annotated

lazy from pydantic import AfterValidator, Field

lazy from ..domain import UNMANAGED_GROUP
lazy from ..services.public_dataset.schema.contract import YOUTUBE_ID_PATTERN
lazy from ..utils.cron import validate_cron_expression

#: An 11-character YouTube video ID, as the catalog contract defines it.
type YouTubeId = Annotated[str, Field(pattern=YOUTUBE_ID_PATTERN.pattern)]


def _unique[T](values: list[T]) -> list[T]:
    """Drop repeated values, keeping the first of each in order."""
    return list(dict.fromkeys(values))


#: A list whose repeated values are dropped, keeping the first of each.
type UniqueList[T] = Annotated[list[T], AfterValidator(_unique)]

#: Media-server library identifiers, without repeats.
type LibraryIds = Annotated[
    UniqueList[Annotated[str, Field(min_length=1, max_length=128)]],
    Field(max_length=200),
]


#: A five-field crontab expression, with its whitespace normalised.
type CronExpression = Annotated[str, AfterValidator(validate_cron_expression)]


def check_group_name(name: str) -> str:
    """Refuse the virtual Unmanaged group's name for a stored group.

    Raises:
        ValueError: When *name* is the reserved name, in any case.
    """
    if name.strip().casefold() == UNMANAGED_GROUP.casefold():
        raise ValueError(
            f'"{UNMANAGED_GROUP}" is reserved for collections without rules'
        )
    return name


#: A collection group name other than the reserved Unmanaged.
type GroupName = Annotated[str, Field(max_length=200), AfterValidator(check_group_name)]
