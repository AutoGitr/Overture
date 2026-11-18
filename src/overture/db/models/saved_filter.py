"""SavedFilter model - custom library filters saved under a name."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, SQLModel, UniqueConstraint

lazy from ...domain import MediaType
lazy from ..columns import enum_type, typed_columns


class SavedFilter(SQLModel, table=True):
    """A custom filter of library titles, saved under a name.

    It is offered for every media type whose titles can be tested by all its
    conditions.
    """

    __tablename__: ClassVar[Any] = "saved_filters"
    __table_args__ = (UniqueConstraint("name", name="uq_saved_filters_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    #: The media type its TMDB IDs name; null when it names no titles by ID.
    media_type: MediaType | None = Field(default=None, sa_type=enum_type(MediaType))
    #: A ``FilterGroup`` of field and source conditions.
    criteria: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(nullable=False)
    updated_at: datetime = Field(nullable=False)


typed_columns(SavedFilter)
