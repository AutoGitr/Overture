"""DownloadJob model - tracks art and theme download jobs."""

lazy import uuid
lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import Field, Index, Relationship, SQLModel

lazy from ...domain import ArtType, JobStatus, JobType
lazy from ..columns import enum_columns, enum_type
lazy from .media_item import MediaItem
lazy from .season import Season


def _uuid() -> str:
    """Return a new UUID string for job IDs."""
    return str(uuid.uuid4())


class DownloadJobBase(SQLModel):
    """Base model holding download job fields."""

    media_item_id: int | None = Field(
        default=None,
        foreign_key="media_items.id",
        ondelete="CASCADE",
        index=True,
        nullable=True,
    )
    job_type: JobType = Field(sa_type=enum_type(JobType))
    art_type: ArtType | None = Field(default=None, sa_type=enum_type(ArtType))
    target_url: str | None = None
    season_id: int | None = Field(
        default=None,
        foreign_key="seasons.id",
        ondelete="CASCADE",
    )
    collection_id: int | None = Field(
        default=None, foreign_key="media_collections.id", ondelete="CASCADE", index=True
    )
    collection_title: str | None = None
    status: JobStatus = Field(
        default=JobStatus.PENDING,
        sa_type=enum_type(JobStatus),
        index=True,
    )
    progress_percent: float = Field(default=0.0)
    error_message: str | None = None
    created_at: datetime = Field(nullable=False)
    completed_at: datetime | None = None


class DownloadJob(DownloadJobBase, table=True):
    """Store download job rows in the application database."""

    __tablename__: ClassVar[Any] = "download_jobs"
    __table_args__ = (
        Index(
            "ix_download_jobs_active_equivalent",
            "media_item_id",
            "job_type",
            "art_type",
            "target_url",
            "season_id",
            "status",
        ),
        Index("ix_download_jobs_status_created", "status", "created_at"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)

    media_item: Optional["MediaItem"] = Relationship(
        back_populates="download_jobs",
        sa_relationship_kwargs={"lazy": "raise"},
    )
    season: Optional["Season"] = Relationship(
        back_populates="download_jobs",
        sa_relationship_kwargs={"lazy": "raise"},
    )


enum_columns(DownloadJob)
