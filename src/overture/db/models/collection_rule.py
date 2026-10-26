"""The criteria that maintain one collection's members."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel

lazy from ...domain import (
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    SyncMode,
)
lazy from ..columns import enum_columns, enum_type


class CollectionRule(SQLModel, table=True):
    """Criteria, evaluated by Overture or by Plex, and nullable policy overrides."""

    __tablename__: ClassVar[Any] = "collection_rules"

    id: int | None = Field(default=None, primary_key=True)
    collection_id: int = Field(
        foreign_key="media_collections.id", ondelete="CASCADE", unique=True, index=True
    )
    #: A ``FilterGroup`` of field and source conditions.
    criteria_json: str
    smart: bool = False
    item_limit: int | None = None
    sync_mode: SyncMode | None = Field(default=None, sa_type=enum_type(SyncMode))
    minimum_items: int | None = None
    delete_below_minimum: bool | None = None
    collection_mode: CollectionMode | None = Field(
        default=None, sa_type=enum_type(CollectionMode)
    )
    order_type: CollectionOrder | None = Field(
        default=None, sa_type=enum_type(CollectionOrder)
    )
    collection_filtering: CollectionFiltering | None = Field(
        default=None, sa_type=enum_type(CollectionFiltering)
    )
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    sort_title_format: str | None = None
    summary_format: str | None = None
    active_start_mmdd: str | None = None
    active_end_mmdd: str | None = None
    delete_when_inactive: bool | None = None
    auto_match_art: bool | None = None
    auto_match_theme: bool | None = None
    sync_interval_hours: int = Field(default=24)
    last_synced_at: datetime | None = None
    last_error: str | None = None
    enabled: bool = True


enum_columns(CollectionRule)
