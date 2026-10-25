"""Sync REST schemas."""

lazy from datetime import datetime
lazy from typing import Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import IncrementalThemeOrder
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope
lazy from .schedules import ScheduleResponseBase, ScheduleWrite
lazy from .validators import LibraryIds

#: ``full`` reconciles whole libraries; ``incremental`` polls for new media.
type SyncScheduleMode = Literal["full", "incremental"]


class SyncRunRequest(StrictBaseModel):
    """Validate the sync run request payload."""

    library_ids: LibraryIds | None = None
    include_collections: bool = True


class SyncScheduleConfig(StrictBaseModel):
    """What one saved sync schedule runs."""

    mode: SyncScheduleMode = "full"
    include_collections: bool = True
    library_ids: LibraryIds = Field(
        default_factory=list[str],
        description="Libraries to sync; empty means every library.",
    )
    download_overturedb_art: bool = Field(
        default=False,
        description="Incremental only: queue OvertureDB art for new items.",
    )
    download_themes: IncrementalThemeOrder = Field(
        default=IncrementalThemeOrder.OFF,
        description="Incremental only: queue themes for new items.",
    )

    @model_validator(mode="after")
    def validate_downloads(self) -> Self:
        """New-media downloads only exist for incremental polling."""
        if self.mode == "full" and (
            self.download_overturedb_art
            or self.download_themes is not IncrementalThemeOrder.OFF
        ):
            raise ValueError("Downloads apply only to incremental schedules")
        return self


class SyncScheduleWrite(ScheduleWrite[SyncScheduleConfig]):
    """Create or update a saved sync schedule."""


class IncrementalSyncState(StrictBaseModel):
    """Checkpoint and last-poll figures an incremental schedule keeps."""

    checkpoint: datetime | None = None
    last_duration_seconds: float | None = None
    last_items_added: int | None = None
    last_downloads: int | None = None


class SyncScheduleResponse(ScheduleResponseBase):
    """Saved sync schedule response."""

    kind: Literal["sync"] = "sync"
    config: SyncScheduleConfig
    state: IncrementalSyncState


class SyncStatusResponse(StrictBaseModel):
    """Sync status response."""

    running: bool


class SyncJobEvent(JobEnvelope):
    """WebSocket payload for sync lifecycle events."""

    done: int | None = None
    total: int | None = None
    added: int | None = None
    updated: int | None = None
    unchanged: int | None = None
    removed: int | None = None
    errors: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
