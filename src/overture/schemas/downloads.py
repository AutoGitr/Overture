"""Download REST and WebSocket schemas."""

lazy from typing import Annotated, Literal

lazy from pydantic import Field

lazy from ..domain import MediaType
lazy from ..jobs.kinds import DownloadStatus, JobKind
lazy from .base import StrictBaseModel
lazy from .common import PublicError


class ItemDownloadTarget(StrictBaseModel):
    """Target for a media-item artwork or theme download."""

    target_type: Literal["item"]
    media_item_id: int
    title: str | None = None
    season_id: int | None = None
    job_type: str | None = None
    art_type: str | None = None


class CollectionThemeDownloadTarget(StrictBaseModel):
    """Target for a media-server collection theme upload."""

    target_type: Literal["collection_theme"]
    collection_server_id: str
    media_type: MediaType
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
    #: On completion: the download matched the local file, so nothing was written.
    unchanged: bool | None = None


class DownloadJobsPage(StrictBaseModel):
    """One bounded page of the durable active backlog."""

    items: list[DownloadJobEvent]
    next_cursor: str | None = None
