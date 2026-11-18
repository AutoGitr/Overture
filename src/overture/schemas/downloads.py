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
    #: Where the download comes from: the art's host, or YouTube.
    source: str | None = None


class CollectionDownloadTarget(StrictBaseModel):
    """Target for a collection's artwork or theme, uploaded to its server copies."""

    target_type: Literal["collection"]
    collection_id: int
    title: str
    job_type: Literal[JobType.COLLECTION_ART, JobType.COLLECTION_THEME]
    #: The slot a collection art download fills; none for a theme.
    art_type: ArtType | None = None
    #: Where the download comes from: the art's host, or YouTube.
    source: str | None = None


DownloadJobTarget = Annotated[
    ItemDownloadTarget | CollectionDownloadTarget,
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
