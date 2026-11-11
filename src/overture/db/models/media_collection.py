"""MediaCollection model - media-server collections and their members."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import (
    JSON,
    Field,
    ForeignKeyConstraint,
    Index,
    Relationship,
    SQLModel,
    UniqueConstraint,
)

lazy from ...domain import (
    ArtType,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    MediaType,
    ThemeBulkSource,
)
lazy from ..columns import enum_type, typed_columns
lazy from .art import ArtSlot
lazy from .collection_group import CollectionGroup
lazy from .collection_rule import CollectionRule
lazy from .download_job import DownloadJob
lazy from .library import Library
lazy from .media_item import MediaItem
lazy from .shared import ThemeColumns


class MediaCollection(ThemeColumns, table=True):
    """One collection as Overture shows it, across every library it spans."""

    __tablename__: ClassVar[Any] = "media_collections"

    id: int | None = Field(default=None, primary_key=True)

    kind: CollectionKind = Field(
        default=CollectionKind.REGULAR, sa_type=enum_type(CollectionKind)
    )
    title: str = Field(default="", nullable=False)
    summary: str | None = None
    summary_source: str | None = None
    sort_title: str | None = None
    sort_title_format: str | None = None
    summary_format: str | None = None
    #: The group of a managed collection; an unmanaged one has none.
    group_id: int | None = Field(
        default=None,
        foreign_key="collection_groups.id",
        ondelete="RESTRICT",
        index=True,
    )
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
    # The server's folder for the collection (Jellyfin BoxSets).
    server_path: str | None = None
    server_added_at: datetime | None = None

    # TMDB collection ID the server itself names, such as a BoxSet's.
    provider_tmdb_id: int | None = None
    tmdb_collection_id: int | None = Field(default=None, index=True)
    #: The value its group's collection set created it for.
    generated_value: str | None = None

    #: Where the theme Overture installed was found.
    youtube_id_source: ThemeBulkSource | None = Field(
        default=None, sa_type=enum_type(ThemeBulkSource)
    )

    # Plex's uploaded theme identity. Folder themes use local file facts.
    server_theme_id: str | None = None
    last_matched_at: datetime | None = None

    # Whether the collection is included in theme workflows.
    monitored: bool = Field(default=True, nullable=False)
    #: Excluded by its collection set; kept off the server until selected again
    #: or deleted.
    deselected: bool = Field(default=False, nullable=False)
    # Saved in Overture and not yet sent to the server. Library syncs keep the
    # saved choices, and the scheduler never creates a collection still unsynced.
    unsynced: bool = Field(default=False, nullable=False)

    # Unset until a sync lists the collection; such rows are not shown.
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    group: Optional["CollectionGroup"] = Relationship(
        back_populates="collections",
        sa_relationship_kwargs={"lazy": "joined"},
    )
    rule: Optional["CollectionRule"] = Relationship(
        back_populates="collection",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "joined", "uselist": False},
    )
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
    download_jobs: list["DownloadJob"] = Relationship(
        back_populates="collection",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )
    memberships: list["MediaCollectionMember"] = Relationship(
        back_populates="collection",
        cascade_delete=True,
        sa_relationship_kwargs={
            "lazy": "raise",
            "order_by": "MediaCollectionMember.position",
        },
    )

    @property
    def group_name(self) -> str | None:
        return self.group.name if self.group else None

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
        ForeignKeyConstraint(
            ["library_id", "media_type"],
            ["libraries.id", "libraries.media_type"],
            ondelete="RESTRICT",
            name="fk_collection_libraries_library",
        ),
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
    criteria: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    collection: "MediaCollection" = Relationship(back_populates="libraries")
    # Read only: the media type is the part's own, which the key shares.
    library: Optional["Library"] = Relationship(
        sa_relationship_kwargs={"lazy": "raise", "viewonly": True}
    )


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

    collection: "MediaCollection" = Relationship(
        back_populates="memberships",
        sa_relationship_kwargs={"lazy": "raise"},
    )
    media_item: "MediaItem" = Relationship(
        back_populates="memberships",
        sa_relationship_kwargs={"lazy": "raise"},
    )


typed_columns(MediaCollection)
typed_columns(CollectionLibrary)
