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
    media_type: MediaType
    criteria: FilterGroup


class SavedFilterRead(SavedFilterWrite):
    """A saved custom filter."""

    id: int
