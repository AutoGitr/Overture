"""Artwork slot table - one row per owner and art type.

Items, seasons and collections own artwork through a foreign key, so
deleting an owner takes its artwork with it at the database level.
The payload columns let :mod:`overture.db.art_slots` treat all owners
uniformly.
"""

lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import (
    AutoString,
    CheckConstraint,
    Field,
    Relationship,
    SQLModel,
    UniqueConstraint,
)

lazy from ...domain import ArtStyle, ArtType
lazy from ...utils.art_urls import PublicArtUrl
lazy from ..columns import enum_type, typed_columns
lazy from .media_collection import MediaCollection
lazy from .media_item import MediaItem
lazy from .season import Season


class ArtSlot(SQLModel, table=True):
    """Artwork belonging to exactly one item, season or collection."""

    __tablename__: ClassVar[Any] = "art_slots"
    __table_args__ = (
        CheckConstraint(
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL) "
            "+ (collection_id IS NOT NULL) = 1",
            name="ck_art_slots_owner",
        ),
        CheckConstraint(
            "url IS NULL OR upload_hash IS NULL", name="ck_art_slots_selection"
        ),
        CheckConstraint(
            "generated_style IS NULL OR upload_hash IS NOT NULL",
            name="ck_art_slots_generated",
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
    # SQLModel maps no NewType; the column stays text. Typed so only a link
    # ``public_art_url`` checked can be assigned to it.
    url: PublicArtUrl | None = Field(default=None, sa_type=AutoString)
    #: The selection is an image someone uploaded, kept in the image cache
    #: under this hash. A slot selects a link or an upload, never both.
    upload_hash: str | None = None
    #: The selected upload is one Overture drew in this style from the
    #: owner's title, and draws again when the title changes.
    generated_style: ArtStyle | None = Field(default=None, sa_type=enum_type(ArtStyle))
    file_hash: str | None = None
    phash: str | None = None
    width: int | None = None
    height: int | None = None
    file_mtime_ns: int | None = None
    file_size: int | None = None

    media_item: Optional["MediaItem"] = Relationship(back_populates="art_slots")
    season: Optional["Season"] = Relationship(back_populates="art_slots")
    collection: Optional["MediaCollection"] = Relationship(back_populates="art_slots")


typed_columns(ArtSlot)
