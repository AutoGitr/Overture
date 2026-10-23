"""Download REST and WebSocket schemas."""

lazy from typing import Annotated, Literal

lazy from pydantic import Field

lazy from ..domain import ArtType, JobType
lazy from ..jobs.kinds import DownloadStatus, JobKind
lazy from .base import StrictBaseModel
lazy from .common import PublicError


class ItemDownloadTarget(StrictBaseModel):
    """Target for a media-item artwork or theme download."""

    target_type: Literal["item"]
    media_item_id: int
    title: str | None = None
    season_id: int | None = None
    job_type: Literal[JobType.ART, JobType.THEME] | None = None
    art_type: ArtType | None = None


class CollectionThemeDownloadTarget(StrictBaseModel):
    """Target for a media-server collection theme upload."""

    target_type: Literal["collection_theme"]
    collection_id: int
    title: str


DownloadJobTarget = Annotated[
    ItemDownloadTarget | CollectionThemeDownloadTarget,
    Field(discriminator="target_type"),
]


class DownloadJobMetadata(StrictBaseModel):
    """Canonical metadata for item and collection download events."""

    kind: Literal[JobKind.DOWNLOAD]
    status: DownloadStatus
    id: str
    target: DownloadJobTarget
    error: PublicError | None = None


class DownloadJobEvent(StrictBaseModel):
    """Download manager lifecycle event."""

    job: DownloadJobMetadata
    percent: float | int | None = None
    stage: str | None = None
    #: While running: the step the download is on, counted from 1, of *steps*.
    step: int | None = None
    steps: int | None = None
    #: On completion: the download matched the local file, so nothing was written.
    unchanged: bool | None = None
