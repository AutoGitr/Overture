"""Custom library filters: criteria the library is filtered by, and saved ones."""

lazy from typing import Annotated

lazy from pydantic import Field

lazy from ..domain import MediaType
lazy from .base import StrictBaseModel
lazy from .collections import (
    CollectionFieldRead,
    CollectionSourceRead,
    Condition,
    FilterGroup,
)
lazy from .validators import DisplayName


class LibraryFilterCapabilities(StrictBaseModel):
    """The fields and sources a custom filter of the library's titles can test."""

    fields: list[CollectionFieldRead]
    sources: list[CollectionSourceRead]


class LibraryFilterMatchRequest(StrictBaseModel):
    """A custom filter's metadata and source conditions, to test one by one.

    Library status conditions, and how conditions combine, are evaluated in
    the browser against the live library list.
    """

    media_type: MediaType
    conditions: Annotated[list[Condition], Field(max_length=200)]


class LibraryFilterMatch(StrictBaseModel):
    """The titles each condition selects, in the order of the request's."""

    item_ids: list[list[int]]


class SavedFilterWrite(StrictBaseModel):
    """A custom filter to save under a name."""

    name: DisplayName
    criteria: FilterGroup
    #: The media type it is made for, which TMDB IDs in it name.
    media_type: MediaType


class SavedFilterRead(StrictBaseModel):
    """A saved custom filter."""

    id: int
    name: str
    criteria: FilterGroup
    #: The media type its TMDB IDs name; null when it names no titles by ID.
    media_type: MediaType | None
    #: The media types whose titles every condition can test, where it is offered.
    media_types: list[MediaType]
    #: Why it is not offered for each other media type.
    unavailable: dict[MediaType, str]
