"""Realtime snapshot REST and WebSocket schemas."""

lazy from pydantic import Field

lazy from ..utils.types import JsonValue
lazy from .base import StrictBaseModel
lazy from .downloads import DownloadJobEvent
lazy from .public_dataset import PublicDatasetStatus


class RealtimeJobSnapshot(StrictBaseModel):
    """One managed-job event used to restore a browser view."""

    event: str
    data: dict[str, JsonValue]


class RealtimeSnapshot(StrictBaseModel):
    """Process-local realtime state at one event-stream watermark."""

    epoch: str
    sequence: int
    # When the server built this snapshot; browsers measure their clock offset from it.
    server_time: str
    jobs: list[RealtimeJobSnapshot] = Field(default_factory=list[RealtimeJobSnapshot])
    #: Every queued and running download, in the order they were queued.
    downloads: list[DownloadJobEvent] = Field(default_factory=list[DownloadJobEvent])
    public_dataset_status: PublicDatasetStatus
