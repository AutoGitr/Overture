"""Nullable defaults for the collections in one group."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, Relationship, UniqueConstraint

lazy from ..columns import typed_columns
lazy from .media_collection import MediaCollection
lazy from .shared import PolicyOverrides


class CollectionGroup(PolicyOverrides, table=True):
    """A collection group's defaults, kept apart from each collection's own choices."""

    __tablename__: ClassVar[Any] = "collection_groups"
    __table_args__ = (UniqueConstraint("name", name="uq_collection_group"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str
    #: A ``CollectionGenerator`` that makes the group a collection set.
    generator: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    #: When the set last created and updated its collections.
    generated_at: datetime | None = None
    #: An empty collection titled after the group heads its collections.
    separator: bool = Field(default=False, nullable=False)

    collections: list["MediaCollection"] = Relationship(
        back_populates="group",
        sa_relationship_kwargs={"lazy": "raise"},
    )


typed_columns(CollectionGroup)
