"""Nullable defaults for collections in one group on one media server."""

lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel, UniqueConstraint

lazy from ...domain import CollectionMode, MediaType, ServerType, SyncMode
lazy from ..columns import enum_columns, enum_type


class CollectionGroup(SQLModel, table=True):
    """Keep group policy separate from a collection's explicit choices."""

    __tablename__: ClassVar[Any] = "collection_groups"
    __table_args__ = (UniqueConstraint("server_type", "media_type", "name"),)

    id: int | None = Field(default=None, primary_key=True)
    server_type: ServerType = Field(sa_type=enum_type(ServerType))
    media_type: MediaType = Field(sa_type=enum_type(MediaType))
    name: str
    sync_mode: SyncMode | None = Field(default=None, sa_type=enum_type(SyncMode))
    minimum_items: int | None = None
    delete_below_minimum: bool | None = None
    collection_mode: CollectionMode | None = Field(
        default=None, sa_type=enum_type(CollectionMode)
    )
    sort_title_format: str | None = None
    auto_match_art: bool | None = None
    auto_match_theme: bool | None = None


enum_columns(CollectionGroup)
