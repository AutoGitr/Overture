"""The rule that maintains one collection's members."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field

lazy from ..columns import typed_columns
lazy from .shared import PolicyOverrides


class CollectionRule(PolicyOverrides, table=True):
    """How a collection's criteria are evaluated, and nullable policy overrides.

    Each library's criteria are stored with that library.
    """

    __tablename__: ClassVar[Any] = "collection_rules"

    id: int | None = Field(default=None, primary_key=True)
    collection_id: int = Field(
        foreign_key="media_collections.id", ondelete="CASCADE", unique=True, index=True
    )
    #: Plex evaluates each library's criteria live instead of Overture on each sync.
    smart: bool = False
    #: The most members taken from each library.
    item_limit: int | None = None
    #: The description of the first list the criteria use, for summaries.
    source_summary: str | None = None
    last_synced_at: datetime | None = None
    last_error: str | None = None


typed_columns(CollectionRule)
