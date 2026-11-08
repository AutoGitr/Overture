"""MediaItem model - movies and shows."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import (
    CheckConstraint,
    Field,
    ForeignKeyConstraint,
    Index,
    Relationship,
    UniqueConstraint,
)

lazy from ...domain import MediaType, TermKind, ThemeIdSource
lazy from ..columns import enum_type, typed_columns
lazy from .art import ArtSlot
lazy from .download_job import DownloadJob
lazy from .library import Library
lazy from .season import Season
lazy from .shared import ThemeColumns
lazy from .term import MediaItemTerm


class MediaItem(ThemeColumns, table=True):
    """A movie or TV show of the media server's libraries."""

    __tablename__: ClassVar[Any] = "media_items"
    __table_args__ = (
        # Movies and shows share the table; each keeps the other's fields empty.
        CheckConstraint(
            "media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL"
            " AND versions IS NULL AND director_etag IS NULL)",
            name="ck_media_items_movie_fields",
        ),
        CheckConstraint(
            "media_type = 'show' OR (show_status IS NULL AND last_aired IS NULL)",
            name="ck_media_items_show_fields",
        ),
        ForeignKeyConstraint(
            ["library_id", "media_type"],
            ["libraries.id", "libraries.media_type"],
            ondelete="RESTRICT",
            name="fk_media_items_library",
        ),
        # The key seasons reference, so only a show can have them.
        UniqueConstraint("id", "media_type", name="uq_media_items_typed"),
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

    server_item_id: str | None = Field(default=None, index=True)
    server_verified_at: datetime | None = None
    #: The library holding it; none for a title chosen from TMDB alone.
    library_id: str | None = Field(default=None, index=True)

    monitored: bool = Field(default=True, nullable=False)

    #: How the selected video was established.
    youtube_id_source: ThemeIdSource | None = Field(
        default=None, sa_type=enum_type(ThemeIdSource)
    )

    studio: str | None = None
    content_rating: str | None = None
    edition: str | None = None
    resolution: str | None = None
    critic_rating: float | None = None
    audience_rating: float | None = None
    user_rating: float | None = None
    duration_seconds: int | None = None
    #: Play state of the account Overture uses on the media server.
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
    server_removed_at: datetime | None = None

    # Media-server metadata version the stored directors were read at, for
    # servers whose listings omit directors (Jellyfin and Emby).
    director_etag: str | None = None
    theme_provenance_cleared: bool = Field(default=False, nullable=False)
    #: The tmdb_id the TMDB fields describe; a different tmdb_id means they
    #: have to be looked up again, as does an old lookup.
    tmdb_checked_id: int | None = None
    tmdb_checked_at: datetime | None = None

    # Read only: an item's media type is its own, which the key shares.
    library: Optional["Library"] = Relationship(
        sa_relationship_kwargs={"lazy": "raise", "viewonly": True}
    )
    # Relationships. Foreign keys cascade in the database, so a deleted
    # item cannot leave seasons, artwork, values or jobs behind whether the
    # delete goes through the ORM or straight to SQL.
    terms: list["MediaItemTerm"] = Relationship(
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise", "order_by": "MediaItemTerm.position"},
    )
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
        if "terms" not in data:
            self.terms = []

    def values(self, kind: TermKind) -> list[str]:
        """The item's values of *kind*, in order; its terms must be loaded."""
        return [link.term.name for link in self.terms if link.term.kind is kind]


typed_columns(MediaItem)
