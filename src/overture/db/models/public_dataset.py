"""Public dataset models - curated external art and theme metadata."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import CheckConstraint, Field, Index, Relationship, SQLModel

lazy from ...domain import MediaType
lazy from ..columns import enum_columns, enum_type


class PublicDatasetItemBase(SQLModel):
    """Base model holding public dataset item fields."""

    media_type: MediaType = Field(sa_type=enum_type(MediaType), index=True)
    tmdb_id: int | None = Field(default=None, index=True)
    tvdb_id: int | None = Field(default=None, index=True)
    imdb_id: str | None = Field(default=None, index=True)
    title: str | None = None
    year: int | None = None
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    catalog_synced_at: datetime | None = None


class PublicDatasetItem(PublicDatasetItemBase, table=True):
    """Store public dataset item rows in the application database."""

    __tablename__: ClassVar[Any] = "public_dataset_items"
    __table_args__ = (
        Index("ix_public_dataset_item_tmdb", "media_type", "tmdb_id"),
        Index("ix_public_dataset_item_tvdb", "media_type", "tvdb_id"),
        Index("ix_public_dataset_item_imdb", "media_type", "imdb_id"),
        CheckConstraint(
            "youtube_id_overturedb IS NULL "
            "OR youtube_id_themerrdb IS NULL "
            "OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_public_dataset_different_youtube_ids",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    seasons: list["PublicDatasetSeason"] = Relationship(
        back_populates="item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )


class PublicDatasetSeasonBase(SQLModel):
    """Base model holding public dataset season fields."""

    public_dataset_item_id: int | None = Field(
        default=None,
        foreign_key="public_dataset_items.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    season_num: int = Field(index=True)
    poster_url: str | None = None


class PublicDatasetSeason(PublicDatasetSeasonBase, table=True):
    """Store public dataset season rows in the application database."""

    __tablename__: ClassVar[Any] = "public_dataset_seasons"
    __table_args__ = (
        Index(
            "ix_public_dataset_season_item_number",
            "public_dataset_item_id",
            "season_num",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    item: Optional["PublicDatasetItem"] = Relationship(back_populates="seasons")


enum_columns(PublicDatasetItem)
