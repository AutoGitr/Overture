"""CollectionTheme model - tracks theme music for media server collections."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, Index, SQLModel, UniqueConstraint

lazy from ...domain import MediaType, ServerType
lazy from ..columns import enum_columns, enum_type


class CollectionThemeBase(SQLModel):
    """Base model holding collection theme fields."""

    # Composite identity: provider item ID plus collection media type.
    server_item_id: str = Field(nullable=False, index=True)

    media_type: MediaType = Field(sa_type=enum_type(MediaType), index=True)

    # Which media server supplied this collection
    server_type: ServerType = Field(sa_type=enum_type(ServerType))

    # Source metadata for the theme installed through Overture.
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None

    # Provider identity of that exact installed theme. A mismatch means the
    # provider theme was replaced outside Overture and invalidates the source.
    server_theme_id: str | None = None

    # Whether the collection is included in theme workflows.
    monitored: bool = Field(default=True, nullable=False)

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CollectionTheme(CollectionThemeBase, table=True):
    """Stores YouTube theme assignments for media-server collections."""

    __tablename__: ClassVar[Any] = "collection_themes"
    __table_args__ = (
        UniqueConstraint(
            "server_item_id",
            "media_type",
            name="uq_collection_theme_server_media",
        ),
        Index("ix_collection_themes_server_media", "server_item_id", "media_type"),
    )

    id: int | None = Field(default=None, primary_key=True)


enum_columns(CollectionTheme)
