"""MediaItem model - movies and shows."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlalchemy import JSON
lazy from sqlmodel import Field, Index, Relationship, SQLModel

lazy from ...domain import MediaType, ThemeIdSource
lazy from ..columns import enum_columns, enum_type
lazy from .art import ArtSlot
lazy from .download_job import DownloadJob
lazy from .season import Season


class MediaItemBase(SQLModel):
    """Base model holding media item fields."""

    media_type: MediaType = Field(sa_type=enum_type(MediaType), index=True)
    title: str = Field(nullable=False, index=True)
    year: int | None = None
    tmdb_id: int | None = Field(default=None, index=True)
    tvdb_id: int | None = None
    imdb_id: str | None = None
    #: The TMDB collection a movie belongs to.
    tmdb_collection_id: int | None = Field(default=None, index=True)

    folder_path: str | None = Field(default=None, index=True)

    server_item_id: str | None = Field(default=None, index=True)
    server_link: str | None = None
    server_verified_at: datetime | None = None
    # Provider library ID, used for library-based filtering.
    library_id: str | None = Field(default=None, index=True)

    monitored: bool = Field(default=True, nullable=False)

    youtube_id: str | None = None
    youtube_id_source: ThemeIdSource | None = Field(
        default=None, sa_type=enum_type(ThemeIdSource)
    )
    youtube_title: str | None = None
    youtube_duration: int | None = Field(
        default=None, description="Duration in seconds"
    )
    theme_file_hash: str | None = None

    director: str | None = None
    studio: str | None = None
    genres: list[str] = Field(default_factory=list, sa_type=JSON)
    actors: list[str] = Field(default_factory=list, sa_type=JSON)
    writers: list[str] = Field(default_factory=list, sa_type=JSON)
    producers: list[str] = Field(default_factory=list, sa_type=JSON)
    countries: list[str] = Field(default_factory=list, sa_type=JSON)
    labels: list[str] = Field(default_factory=list, sa_type=JSON)
    tags: list[str] = Field(default_factory=list, sa_type=JSON)
    content_rating: str | None = None
    resolution: str | None = None
    audio_language: str | None = None
    rating: float | None = None
    duration_minutes: int | None = None
    unplayed: bool | None = None
    in_progress: bool | None = None
    release_date: str | None = None

    last_synced_at: datetime | None = None
    last_matched_at: datetime | None = None
    created_at: datetime | None = None
    server_added_at: datetime | None = None
    server_removed_at: datetime | None = None


class MediaItem(MediaItemBase, table=True):
    """Store media item rows in the application database."""

    __tablename__: ClassVar[Any] = "media_items"
    __table_args__ = (
        Index("ix_media_items_server_identity", "media_type", "server_item_id"),
        Index("ix_media_items_tmdb_identity", "media_type", "tmdb_id"),
        Index("ix_media_items_tvdb_identity", "media_type", "tvdb_id"),
        Index("ix_media_items_imdb_identity", "media_type", "imdb_id"),
        Index("ix_media_items_title_year", "media_type", "title", "year"),
        Index("ix_media_items_visible_title", "server_removed_at", "title"),
        Index("ix_media_items_visible_library", "server_removed_at", "library_id"),
        Index("ix_media_items_monitored_library", "monitored", "library_id"),
    )

    id: int | None = Field(default=None, primary_key=True)

    # Media-server metadata version the stored director was read at, for
    # servers whose listings omit directors (Jellyfin and Emby).
    director_etag: str | None = None
    theme_file_mtime_ns: int | None = None
    theme_file_size: int | None = None
    #: Seconds, read from the file at the revision above.
    theme_file_duration: int | None = None
    theme_provenance_cleared: bool = Field(default=False, nullable=False)
    #: The tmdb_id whose collection tmdb_collection_id records; a different
    #: tmdb_id means the collection has to be looked up again.
    tmdb_collection_checked_id: int | None = None

    # Relationships. Foreign keys cascade in the database, so a deleted
    # item cannot leave seasons, artwork, or jobs behind whether the delete goes
    # through the ORM or straight to SQL.
    seasons: list["Season"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )
    art_slots: list["ArtSlot"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    download_jobs: list["DownloadJob"] = Relationship(
        back_populates="media_item",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if "art_slots" not in data:
            self.art_slots = []


enum_columns(MediaItem)
