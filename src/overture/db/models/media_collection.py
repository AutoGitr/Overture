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
    child_count: int = Field(default=0, nullable=False)
    # The lead server copy's image URLs; only their hash leaves the backend, as a
    # cache version.
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
    #: Its set no longer selects its value, so it stays off the server until
    #: the set selects it again; Overture keeps it until it is deleted.
    deselected: bool = Field(default=False, nullable=False)
    # Saved in Overture and not yet sent to the server. Library syncs keep the
    # saved choices, and the scheduler never creates a collection still unsynced.
    unsynced: bool = Field(default=False, nullable=False)

    # Unset until a sync lists the collection; such rows are not shown.
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MediaCollection(MediaCollectionBase, table=True):
    """One collection as Overture shows it, across every library it spans."""

    __tablename__: ClassVar[Any] = "media_collections"

    id: int | None = Field(default=None, primary_key=True)
    art_slots: list["ArtSlot"] = Relationship(
        back_populates="collection",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    libraries: list["CollectionLibrary"] = Relationship(
        back_populates="collection",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "selectin", "order_by": "CollectionLibrary.id"},
    )

    @property
    def server_ids(self) -> list[str]:
        """The server collections holding it, the lead copy first."""
        return list(
            dict.fromkeys(
                part.server_item_id for part in self.libraries if part.server_item_id
            )
        )

    @property
    def server_item_id(self) -> str | None:
        """The lead server copy, whose images and link stand for the collection."""
        return next(iter(self.server_ids), None)

    @property
    def media_types(self) -> list[MediaType]:
        """What its libraries hold, movies first."""
        held = {part.media_type for part in self.libraries}
        return [media_type for media_type in MediaType if media_type in held]

    @property
    def library_ids(self) -> list[str]:
        return [part.library_id for part in self.libraries]

    def server_image_url(self, art_type: ArtType) -> str | None:
        """The server's current poster or background, as sync last saw it."""
        return self.thumb_url if art_type is ArtType.POSTER else self.art_url


class CollectionLibrary(SQLModel, table=True):
    """One library a collection spans, and where the server keeps its members.

    Jellyfin and Emby keep collections outside their libraries, so every
    library of a collection names the same server collection; Plex keeps one
    in each library.
    """

    __tablename__: ClassVar[Any] = "collection_libraries"
    __table_args__ = (
        UniqueConstraint("collection_id", "library_id", name="uq_collection_library"),
    )

    id: int | None = Field(default=None, primary_key=True)
    collection_id: int = Field(
        foreign_key="media_collections.id", ondelete="CASCADE", index=True
    )
    library_id: str
    media_type: MediaType = Field(sa_type=enum_type(MediaType), index=True)
    # Null while the collection is withheld from the server.
    server_item_id: str | None = Field(default=None, index=True)
    #: A ``FilterGroup`` of field and source conditions. Null on a collection
    #: Overture does not manage, and on a library leaving a managed collection
    #: until the next sync removes it from the server.
    criteria_json: str | None = None
    collection: "MediaCollection" = Relationship(back_populates="libraries")


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
enum_columns(CollectionLibrary)
