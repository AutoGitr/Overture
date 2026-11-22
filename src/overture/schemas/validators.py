"""Shared schema field types."""

lazy from typing import Annotated, TypeVar

lazy from pydantic import AfterValidator, Field

lazy from ..catalog_contract.contract import YOUTUBE_ID_PATTERN
lazy from ..domain import UNMANAGED_GROUP
lazy from ..utils.cron import validate_cron_expression
lazy from .base import PositiveId

#: The BLAKE3 hash of an image's bytes, which names it in the image cache.
type ImageHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

#: An 11-character YouTube video ID, as the catalog contract defines it.
type YouTubeId = Annotated[str, Field(pattern=YOUTUBE_ID_PATTERN.pattern)]


def _unique[T](values: list[T]) -> list[T]:
    """Drop repeated values, keeping the first of each in order."""
    return list(dict.fromkeys(values))


_T = TypeVar("_T")

#: A list whose repeated values are dropped, keeping the first of each. A
#: plain alias rather than a ``type`` statement, so FastAPI sees the list in a
#: query model and reads each repeated parameter into it.
UniqueList = Annotated[list[_T], AfterValidator(_unique)]

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

#: Collection groups a run covers, without repeats; at least one when given.
type GroupNames = Annotated[
    UniqueList[Annotated[str, Field(min_length=1, max_length=200)]],
    Field(min_length=1),
]

#: Collections a run or a bulk change names, without repeats; at least one.
type CollectionIds = Annotated[
    UniqueList[PositiveId], Field(min_length=1, max_length=1000)
]


def collapse_name(value: str) -> str:
    """Collapse internal whitespace in a name people give something.

    Raises:
        ValueError: When nothing but whitespace is left.
    """
    name = " ".join(value.split())
    if not name:
        raise ValueError("name is required")
    return name


#: A name someone gives a schedule or a saved filter.
type DisplayName = Annotated[
    str, Field(max_length=100, pattern=r"\S"), AfterValidator(collapse_name)
]
