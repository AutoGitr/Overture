"""MediaCollection model - media-server collections and their members."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, Index, Relationship, SQLModel, UniqueConstraint

lazy from ...domain import (
    ArtType,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    MediaType,
    ServerType,
    ThemeBulkSource,
)
lazy from ..columns import enum_columns, enum_type
lazy from .art import ArtSlot


class MediaCollectionBase(SQLModel):
    """Base model holding media-server collection fields."""

    # Provider IDs are scoped to their server type; public callers use id.
    # Null when a dynamic or seasonal collection is currently withheld from the server.
    server_item_id: str | None = Field(default=None, nullable=True, index=True)

    media_type: MediaType = Field(sa_type=enum_type(MediaType), index=True)

    # Which media server supplied this collection
    server_type: ServerType = Field(sa_type=enum_type(ServerType))

    kind: CollectionKind = Field(
        default=CollectionKind.REGULAR, sa_type=enum_type(CollectionKind)
    )
    title: str = Field(default="", nullable=False)
    summary: str | None = None
    summary_source: str | None = None
    sort_title: str | None = None
    sort_title_format: str | None = None
    summary_format: str | None = None
    collection_group: str | None = Field(default=None, index=True)
    collection_mode: CollectionMode | None = Field(
        default=None, sa_type=enum_type(CollectionMode)
    )
    order_type: CollectionOrder = Field(
        default=CollectionOrder.RELEASE_ASC, sa_type=enum_type(CollectionOrder)
    )
    collection_filtering: CollectionFiltering | None = Field(
        default=None, sa_type=enum_type(CollectionFiltering)
    )
    visible_home: bool = False
    visible_shared: bool = False
    visible_library: bool = False
    active_start_mmdd: str | None = None
    active_end_mmdd: str | None = None
    delete_when_inactive: bool | None = None
    library_id: str | None = Field(default=None, index=True)
    child_count: int = Field(default=0, nullable=False)
    # Server image URLs; only their hash leaves the backend, as a cache version.
    thumb_url: str | None = None
    art_url: str | None = None
    server_link: str | None = None
    # The server's folder for the collection (Jellyfin BoxSets).
    server_path: str | None = None
    server_added_at: datetime | None = None

    # TMDB collection ID the server itself names, such as a BoxSet's.
    provider_tmdb_id: int | None = None
    tmdb_collection_id: int | None = Field(default=None, index=True)
    #: The value its group's collection set created it for.
    generated_value: str | None = None

    # Source metadata for the theme installed through Overture.
    youtube_id: str | None = None
    youtube_id_source: ThemeBulkSource | None = Field(
        default=None, sa_type=enum_type(ThemeBulkSource)
    )
    youtube_title: str | None = None
    youtube_duration: int | None = None

    # Plex's uploaded theme identity. Folder themes use local file facts.
    server_theme_id: str | None = None
    theme_file_hash: str | None = None
    theme_file_mtime_ns: int | None = None
    theme_file_size: int | None = None
    theme_file_duration: int | None = None
    last_matched_at: datetime | None = None

    # Whether the collection is included in theme workflows.
    monitored: bool = Field(default=True, nullable=False)
    # Saved in Overture and not yet sent to the server. Library syncs keep the
    # saved choices, and the scheduler never creates a collection still unsynced.
    unsynced: bool = Field(default=False, nullable=False)

    # Unset until a sync lists the collection; such rows are not shown.
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MediaCollection(MediaCollectionBase, table=True):
    """Stores media-server collections, their TMDB match and their theme."""

    __tablename__: ClassVar[Any] = "media_collections"
    __table_args__ = (
        UniqueConstraint(
            "server_type",
            "server_item_id",
            name="uq_media_collection_server_item",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    art_slots: list["ArtSlot"] = Relationship(
        back_populates="collection",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "selectin"},
    )

    def server_image_url(self, art_type: ArtType) -> str | None:
        """The server's current poster or background, as sync last saw it."""
        return self.thumb_url if art_type is ArtType.POSTER else self.art_url


class MediaCollectionMember(SQLModel, table=True):
    """Links a collection to the stored items it holds."""

    __tablename__: ClassVar[Any] = "media_collection_members"
    __table_args__ = (Index("ix_media_collection_members_item", "media_item_id"),)

    position: int = Field(default=0)
    collection_id: int = Field(
        foreign_key="media_collections.id", ondelete="CASCADE", primary_key=True
    )
    media_item_id: int = Field(
        foreign_key="media_items.id", ondelete="CASCADE", primary_key=True
    )


enum_columns(MediaCollection)
