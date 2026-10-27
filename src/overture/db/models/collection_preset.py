"""Presets people save from their own collections and sets."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel, UniqueConstraint

lazy from ...domain import MediaType
lazy from ..columns import enum_columns, enum_type


class CollectionPreset(SQLModel, table=True):
    """A saved starting point for new collections of one media type."""

    __tablename__: ClassVar[Any] = "collection_presets"
    __table_args__ = (UniqueConstraint("media_type", "label"),)

    id: int | None = Field(default=None, primary_key=True)
    media_type: MediaType = Field(sa_type=enum_type(MediaType))
    label: str
    description: str = ""
    #: A ``CollectionPresetCollection`` or ``CollectionPresetSet``.
    payload_json: str
    created_at: datetime | None = None


enum_columns(CollectionPreset)
