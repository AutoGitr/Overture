"""Season model - show seasons."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import Field, Index, Relationship, SQLModel, UniqueConstraint

lazy from .art import ArtSlot
lazy from .download_job import DownloadJob
lazy from .media_item import MediaItem


class SeasonBase(SQLModel):
    """Base model holding season fields."""

    media_item_id: int = Field(
        foreign_key="media_items.id", ondelete="CASCADE", index=True
    )
    season_num: int = Field(nullable=False)  # 0 = specials
    title: str | None = None
    server_item_id: str | None = None

    file_count: int = Field(default=0, nullable=False)

    folder_path: str | None = None

    last_matched_at: datetime | None = None


class Season(SeasonBase, table=True):
    """Store season rows in the application database."""

    __tablename__: ClassVar[Any] = "seasons"
    __table_args__ = (
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
