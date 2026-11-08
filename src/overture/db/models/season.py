"""Season model - show seasons."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import (
    CheckConstraint,
    Field,
    ForeignKeyConstraint,
    Index,
    Relationship,
    SQLModel,
    UniqueConstraint,
)

lazy from ...domain import MediaType
lazy from ..columns import enum_type, typed_columns
lazy from .art import ArtSlot
lazy from .download_job import DownloadJob
lazy from .media_item import MediaItem


class Season(SQLModel, table=True):
    """One season of a TV show."""

    __tablename__: ClassVar[Any] = "seasons"
    __table_args__ = (
        ForeignKeyConstraint(
            ["media_item_id", "media_type"],
            ["media_items.id", "media_items.media_type"],
            ondelete="CASCADE",
            name="fk_seasons_show",
        ),
        CheckConstraint("media_type = 'show'", name="ck_seasons_show"),
        UniqueConstraint("media_item_id", "season_num", name="uq_season"),
        Index("ix_seasons_item_files", "media_item_id", "file_count"),
        Index(
            "ix_seasons_item_number_files",
            "media_item_id",
            "season_num",
            "file_count",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    media_item_id: int = Field(index=True)
    #: Always a show: with the item's ID it references a show, never a movie.
    media_type: MediaType = Field(
        default=MediaType.SHOW,
        sa_type=enum_type(MediaType),
        sa_column_kwargs={"server_default": MediaType.SHOW.value},
    )
    season_num: int = Field(nullable=False)  # 0 = specials
    title: str | None = None
    server_item_id: str | None = None

    file_count: int = Field(default=0, nullable=False)

    folder_path: str | None = None

    last_matched_at: datetime | None = None

    # Relationships
    media_item: Optional["MediaItem"] = Relationship(
        back_populates="seasons",
        sa_relationship_kwargs={"lazy": "raise"},
    )
    art_slots: list["ArtSlot"] = Relationship(
        back_populates="season",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "selectin"},
    )
    download_jobs: list["DownloadJob"] = Relationship(
        back_populates="season",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "raise"},
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if "art_slots" not in data:
            self.art_slots = []


typed_columns(Season)
