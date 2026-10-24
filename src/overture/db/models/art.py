"""Artwork slot table - one row per owner and art type.

Items, seasons and collections own artwork through a foreign key, so
deleting an owner takes its artwork with it at the database level.
The table carries the payload columns (:class:`ArtSlot`) used by
:mod:`overture.db.art_slots` to treat all owners uniformly.
"""

lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import (
    CheckConstraint,
    Field,
    Relationship,
    SQLModel,
    UniqueConstraint,
)

lazy from ...domain import ArtType
lazy from ..columns import enum_columns, enum_type
lazy from .media_collection import MediaCollection
lazy from .media_item import MediaItem
lazy from .season import Season

#: Payload columns an art slot owns, in the order they are written.
ART_SLOT_FIELDS: tuple[str, ...] = (
    "url",
    "file_hash",
    "phash",
    "width",
    "height",
    "file_mtime_ns",
    "file_size",
)


class ArtSlot(SQLModel, table=True):
    """Artwork belonging to exactly one item, season or collection."""

    __tablename__: ClassVar[Any] = "art_slots"
    __table_args__ = (
        CheckConstraint(
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL) "
            "+ (collection_id IS NOT NULL) = 1",
            name="ck_art_slots_owner",
        ),
        UniqueConstraint("collection_id", "art_type", name="uq_art_slots_collection"),
        UniqueConstraint("media_item_id", "art_type", name="uq_art_slots_media_item"),
        UniqueConstraint("season_id", "art_type", name="uq_art_slots_season"),
    )

    id: int | None = Field(default=None, primary_key=True)
    media_item_id: int | None = Field(
        default=None,
        foreign_key="media_items.id",
        ondelete="CASCADE",
        nullable=True,
        index=True,
    )
    season_id: int | None = Field(
        default=None,
        foreign_key="seasons.id",
        ondelete="CASCADE",
        nullable=True,
        index=True,
    )
    collection_id: int | None = Field(
        default=None,
        foreign_key="media_collections.id",
        ondelete="CASCADE",
        nullable=True,
        index=True,
    )
    art_type: ArtType = Field(sa_type=enum_type(ArtType))
    url: str | None = None
    file_hash: str | None = None
    phash: str | None = None
    width: int | None = None
    height: int | None = None
    file_mtime_ns: int | None = None
    file_size: int | None = None

    media_item: Optional["MediaItem"] = Relationship(back_populates="art_slots")
    season: Optional["Season"] = Relationship(back_populates="art_slots")
    collection: Optional["MediaCollection"] = Relationship(back_populates="art_slots")


enum_columns(ArtSlot)
