"""MediaItem model - movies and shows."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import (
    CheckConstraint,
    Field,
    Index,
    Relationship,
    SQLModel,
)

lazy from ...domain import MediaType
lazy from ..columns import enum_type, typed_columns
lazy from .asset import Asset
lazy from .download_job import DownloadJob
lazy from .media_collection import MediaCollectionMember
lazy from .media_item_copy import MediaItemCopy
lazy from .season import Season


class MediaItem(SQLModel, table=True):
    """A movie or TV show, held by any number of media servers.

    Its metadata describes it as its lead copy does: the copy on the first
    server in MEDIA_SERVERS that lists it. What each server keeps for its own
    copy is in :class:`MediaItemCopy`.
    """

    __tablename__: ClassVar[Any] = "media_items"
    __table_args__ = (
        # Movies and shows share the table; each keeps the other's fields empty.
        CheckConstraint(
            "media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL"
            " AND versions IS NULL)",
            name="ck_media_items_movie_fields",
        ),
        CheckConstraint(
            "media_type = 'show' OR (show_status IS NULL AND last_aired IS NULL)",
            name="ck_media_items_show_fields",
        ),
        Index("ix_media_items_tmdb_identity", "media_type", "tmdb_id"),
        Index("ix_media_items_tvdb_identity", "media_type", "tvdb_id"),
        Index("ix_media_items_imdb_identity", "media_type", "imdb_id"),
        Index("ix_media_items_title_year", "media_type", "title", "year"),
        Index("ix_media_items_visible_title", "server_removed_at", "title"),
    )

    id: int | None = Field(default=None, primary_key=True)
    media_type: MediaType = Field(sa_type=enum_type(MediaType), index=True)
    title: str = Field(nullable=False, index=True)
    #: The server's sort title, which orders titles as the server does.
    sort_title: str | None = None
    year: int | None = None
    tmdb_id: int | None = Field(default=None, index=True)
    tvdb_id: int | None = None
    imdb_id: str | None = None
    #: The TMDB collection a movie belongs to.
    tmdb_collection_id: int | None = Field(default=None, index=True)

    folder_path: str | None = Field(default=None, index=True)

    monitored: bool = Field(default=True, nullable=False)

    studio: str | None = None
    content_rating: str | None = None
    edition: str | None = None
    resolution: str | None = None
    critic_rating: float | None = None
    audience_rating: float | None = None
    user_rating: float | None = None
    duration_seconds: int | None = None
    #: Play state of the account Overture uses on the lead server.
    plays: int | None = None
    last_played_at: datetime | None = None
    unplayed: bool | None = None
    in_progress: bool | None = None
    release_date: str | None = None
    #: Plex lists each version of a movie as its own media.
    versions: int | None = None

    # What TMDB says about the title, read by TMDB enrichment.
    original_language: str | None = None
    tmdb_rating: float | None = None
    tmdb_votes: int | None = None
    show_status: str | None = None
    last_aired: str | None = None

    last_synced_at: datetime | None = None
    last_matched_at: datetime | None = None
    created_at: datetime | None = None
    server_added_at: datetime | None = None
    #: When the last of its copies left its server; a title chosen from TMDB
    #: alone has no copies and is never removed.
    server_removed_at: datetime | None = None

    #: The tmdb_id the TMDB fields describe; a different tmdb_id means they
    #: have to be looked up again, as does an old lookup.
    tmdb_checked_id: int | None = None
    tmdb_checked_at: datetime | None = None

    copies: list["MediaItemCopy"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )
    # Relationships. Foreign keys cascade in the database, so a deleted
    # item cannot leave seasons, artwork, values or jobs behind whether the
    # delete goes through the ORM or straight to SQL.
    seasons: list["Season"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )
    assets: list["Asset"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    download_jobs: list["DownloadJob"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )
    memberships: list["MediaCollectionMember"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if "assets" not in data:
            self.assets = []


typed_columns(MediaItem)
