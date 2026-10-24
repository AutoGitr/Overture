"""Configuration for one dynamic collection builder."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel

lazy from ...domain import RuleSourceType, SyncMode
lazy from ..columns import enum_columns, enum_type


class CollectionRule(SQLModel, table=True):
    """A source and nullable overrides of the global collection defaults."""

    __tablename__: ClassVar[Any] = "collection_rules"

    id: int | None = Field(default=None, primary_key=True)
    collection_id: int = Field(
        foreign_key="media_collections.id", ondelete="CASCADE", unique=True, index=True
    )
    source_type: RuleSourceType = Field(sa_type=enum_type(RuleSourceType))
    source_identifier: str
    filter_json: str | None = None
    sync_mode: SyncMode | None = Field(default=None, sa_type=enum_type(SyncMode))
    minimum_items: int | None = None
    delete_below_minimum: bool | None = None
    sync_interval_hours: int = Field(default=24)
    last_synced_at: datetime | None = None
    last_error: str | None = None
    enabled: bool = True


enum_columns(CollectionRule)
