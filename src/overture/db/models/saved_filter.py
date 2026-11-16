"""SavedFilter model - custom library filters saved under a name."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, SQLModel, UniqueConstraint

lazy from ...domain import MediaType
lazy from ..columns import enum_type, typed_columns


class SavedFilter(SQLModel, table=True):
    """A custom filter of one media type's titles, saved under a name."""

    __tablename__: ClassVar[Any] = "saved_filters"
    __table_args__ = (
        UniqueConstraint("media_type", "name", name="uq_saved_filters_media_type_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    media_type: MediaType = Field(sa_type=enum_type(MediaType))
    name: str = Field(nullable=False)
    #: A ``FilterGroup`` of field and source conditions.
    criteria: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(nullable=False)
    updated_at: datetime = Field(nullable=False)


typed_columns(SavedFilter)
