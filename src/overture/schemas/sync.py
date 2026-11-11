"""Sync REST schemas."""

lazy from datetime import datetime
lazy from typing import Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import IncrementalThemeOrder
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope
lazy from .schedules import ScheduleResponseBase, ScheduleWrite
lazy from .validators import CollectionIds, GroupNames, LibraryIds

#: ``full`` reconciles whole libraries; ``incremental`` polls for new media.
type SyncScheduleMode = Literal["full", "incremental"]


class _SyncCollections(StrictBaseModel):
    """Which collections a full sync covers: every one, a choice of them, or none."""

    include_collections: bool = Field(
        default=True, description="Refresh every collection from the media server."
    )
    collection_groups: GroupNames | None = Field(
        default=None,
        description="Run these groups' sets and sync their collections instead.",
    )
    collection_ids: CollectionIds | None = Field(
        default=None,
        description="Sync these collections instead, whole, besides any groups.",
    )
    items: bool = Field(
        default=True,
        description="Reconcile library items; off syncs only the collections.",
    )

    @property
    def chosen_collections(self) -> bool:
        """Some groups or collections are chosen in place of every collection."""
        return self.collection_groups is not None or self.collection_ids is not None

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        """Every collection already covers each choice; a sync syncs something."""
        if self.include_collections and self.chosen_collections:
            raise ValueError("Select some collections or every collection")
        if not self.items and not (self.include_collections or self.chosen_collections):
            raise ValueError("Select libraries or collections")
        return self


class SyncRunRequest(_SyncCollections):
    """Validate the sync run request payload."""

    library_ids: LibraryIds | None = None


class SyncScheduleConfig(_SyncCollections):
    """What one saved sync schedule runs."""

    mode: SyncScheduleMode = "full"
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
    def validate_mode(self) -> Self:
        """New-media downloads only exist for polling, and groups for a full sync."""
        if self.mode == "full" and (
            self.download_overturedb_art
            or self.download_themes is not IncrementalThemeOrder.OFF
        ):
            raise ValueError("Downloads apply only to incremental schedules")
        if self.mode == "incremental" and (self.chosen_collections or not self.items):
            raise ValueError("Polling looks for new items in libraries")
        return self


class SyncScheduleWrite(ScheduleWrite[SyncScheduleConfig]):
    """Create or update a saved sync schedule."""


class IncrementalSyncState(StrictBaseModel):
    """The checkpoint an incremental schedule polls from."""

    checkpoint: datetime | None = None


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
