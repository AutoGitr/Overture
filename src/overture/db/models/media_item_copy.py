"""MediaItemCopy model - what each media server keeps for its copy of a title."""

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

lazy from ...domain import MediaType
lazy from ..columns import enum_type, typed_columns
lazy from .media_item import MediaItem


class MediaItemCopy(SQLModel, table=True):
    """One media server's copy of a title, and the facts that server keeps for it.

    The title itself (:class:`MediaItem`) is described by its lead copy: the
    one on the first server in MEDIA_SERVERS that lists it.
    """

    __tablename__: ClassVar[Any] = "media_item_copies"
    __table_args__ = (
        UniqueConstraint("media_item_id", "server_id", name="uq_media_item_copy"),
        UniqueConstraint(
            "server_id",
            "media_type",
            "server_item_id",
            name="uq_media_item_copy_server",
        ),
        ForeignKeyConstraint(
            ["library_id", "media_type"],
            ["libraries.id", "libraries.media_type"],
            ondelete="RESTRICT",
            name="fk_media_item_copies_library",
        ),
        Index("ix_media_item_copies_library", "library_id", "removed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    media_item_id: int = Field(
        foreign_key="media_items.id", ondelete="CASCADE", index=True
    )
    server_id: int = Field(foreign_key="media_servers.id", ondelete="RESTRICT")
    media_type: MediaType = Field(sa_type=enum_type(MediaType))
    server_item_id: str
    library_id: str
    added_at: datetime | None = None
    #: When the server's last complete listing left it out.
    removed_at: datetime | None = None
    verified_at: datetime | None = None
    #: Play state and rating of the account Overture uses on this server.
    plays: int | None = None
    last_played_at: datetime | None = None
    unplayed: bool | None = None
    in_progress: bool | None = None
    user_rating: float | None = None
    #: Plex labels, or Jellyfin and Emby tags, on this server.
    labels: list[str] = Field(default_factory=list, sa_type=JSON)
    #: This server's metadata version the stored directors were read at, for
    #: servers whose listings omit directors (Jellyfin and Emby).
    director_etag: str | None = None

    media_item: Optional["MediaItem"] = Relationship(
        back_populates="copies", sa_relationship_kwargs={"lazy": "raise"}
    )


class SeasonCopy(SQLModel, table=True):
    """One media server's ID of a season of a title it holds."""

    __tablename__: ClassVar[Any] = "season_copies"

    season_id: int = Field(
        foreign_key="seasons.id", ondelete="CASCADE", primary_key=True
    )
    server_id: int = Field(
        foreign_key="media_servers.id", ondelete="RESTRICT", primary_key=True
    )
    server_item_id: str


typed_columns(MediaItemCopy)
typed_columns(SeasonCopy)
