"""Catalog models - curated external art and theme metadata."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import JSON, CheckConstraint, Field, Index, Relationship, SQLModel

lazy from ...domain import CatalogMediaType, MediaType
lazy from ..columns import enum_type, typed_columns


class CatalogItem(SQLModel, table=True):
    """An OvertureDB catalog movie or show."""

    __tablename__: ClassVar[Any] = "catalog_items"
    __table_args__ = (
        Index("ix_catalog_item_tmdb", "media_type", "tmdb_id"),
        Index("ix_catalog_item_tvdb", "media_type", "tvdb_id"),
        Index("ix_catalog_item_imdb", "media_type", "imdb_id"),
        CheckConstraint(
            "youtube_id_overturedb IS NULL "
            "OR youtube_id_themerrdb IS NULL "
            "OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_catalog_item_different_youtube_ids",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
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
    #: OvertureDB says the title has no theme music.
    no_theme: bool = False
    catalog_synced_at: datetime | None = None

    seasons: list["CatalogItemSeason"] = Relationship(
        back_populates="item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )


class CatalogItemSeason(SQLModel, table=True):
    """A season of an OvertureDB catalog show."""

    __tablename__: ClassVar[Any] = "catalog_item_seasons"
    __table_args__ = (
        Index(
            "ix_catalog_item_season_number",
            "catalog_item_id",
            "season_num",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    catalog_item_id: int | None = Field(
        default=None,
        foreign_key="catalog_items.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    season_num: int = Field(index=True)
    poster_url: str | None = None

    item: Optional["CatalogItem"] = Relationship(back_populates="seasons")


class CatalogCollection(SQLModel, table=True):
    """An OvertureDB catalog movie collection, by its TMDB collection."""

    __tablename__: ClassVar[Any] = "catalog_collections"
    __table_args__ = (
        CheckConstraint(
            "youtube_id_overturedb IS NULL "
            "OR youtube_id_themerrdb IS NULL "
            "OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_catalog_collection_different_youtube_ids",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    tmdb_id: int = Field(unique=True)
    title: str
    poster_url: str | None = None
    background_url: str | None = None
    #: The poster in the layout every consistent collection poster shares.
    consistent_poster_url: str | None = None
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
    #: OvertureDB says the collection has no theme music.
    no_theme: bool = False
    catalog_synced_at: datetime | None = None


class CatalogDraft(SQLModel, table=True):
    """A local change to a catalog entry, waiting to be contributed.

    The draft holds the whole proposed entry and every identifier it has, so
    it still finds its catalog entry after that entry is renamed.
    """

    __tablename__: ClassVar[Any] = "catalog_drafts"

    id: int | None = Field(default=None, primary_key=True)
    media_type: CatalogMediaType = Field(
        sa_type=enum_type(CatalogMediaType), index=True
    )
    tmdb_id: int | None = Field(default=None, index=True)
    tvdb_id: int | None = Field(default=None, index=True)
    imdb_id: str | None = Field(default=None, index=True)
    entry: dict[str, Any] = Field(sa_type=JSON)
    updated_at: datetime


typed_columns(CatalogItem)
typed_columns(CatalogDraft)
