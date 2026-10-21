"""Typed WebSocket event registry and payload validation."""

lazy from dataclasses import dataclass
lazy from typing import Any, cast

lazy from pydantic import BaseModel

lazy from ..jobs.kinds import JobKind, LifecycleStatus
lazy from ..schemas.asset_manager import AssetScanProgressEvent
lazy from ..schemas.backup import BackupJobEvent
lazy from ..schemas.bulk import BulkArtJobEvent, BulkThemeJobEvent
lazy from ..schemas.collections import CollectionThemeUpdatedEvent
lazy from ..schemas.common import JsonValue
lazy from ..schemas.downloads import DownloadJobEvent
lazy from ..schemas.job_snapshots import JobSnapshotClearedEvent
lazy from ..schemas.library import (
    BulkItemOperationResult,
    ItemUpdatedEvent,
    LibraryItemRemovedEvent,
    LibraryItemUpsertedEvent,
)
lazy from ..schemas.public_dataset import PublicDatasetStatus, PublicDatasetSyncEvent
lazy from ..schemas.realtime import RealtimeSnapshot
lazy from ..schemas.schedules import SchedulesChangedEvent
lazy from ..schemas.server_audit import ServerAuditFixEvent, ServerAuditProgressEvent
lazy from ..schemas.sync import SyncJobEvent


@dataclass(slots=True, frozen=True)
class WebSocketEventDefinition:
    """Registered WebSocket event metadata."""

    name: str
    payload_model: type[BaseModel] | None
    snapshot: bool = False
    #: Job events omit their null fields to keep progress payloads small.
    #: Events whose payload *is* a read model must not, because the client
    #: stores them directly in the REST cache and a partial object would
    #: blank out fields that are already known.
    exclude_none: bool = True


def _lifecycle_events(
    kind: JobKind, payload_model: type[BaseModel]
) -> dict[str, WebSocketEventDefinition]:
    """Build the lifecycle event definitions for one managed job kind.

    The runner decides between the statuses, and the slot itself publishes
    ``stopped`` or ``failed`` for a run that was cancelled or crashed, so
    every job registers all of them rather than the subset its happy path
    happens to use.
    """
    return {
        f"{kind.event_prefix}.{status}": WebSocketEventDefinition(
            f"{kind.event_prefix}.{status}",
            payload_model,
            snapshot=status.terminal,
        )
        for status in LifecycleStatus
    }


EVENT_REGISTRY: frozendict[str, WebSocketEventDefinition] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "ping": WebSocketEventDefinition("ping", None),
        "realtime.snapshot": WebSocketEventDefinition(
            "realtime.snapshot",
            RealtimeSnapshot,
            exclude_none=False,
        ),
        **_lifecycle_events(JobKind.SYNC, SyncJobEvent),
        **_lifecycle_events(JobKind.BULK_ART, BulkArtJobEvent),
        **_lifecycle_events(JobKind.BULK_THEME, BulkThemeJobEvent),
        **_lifecycle_events(JobKind.ASSET_SCAN, AssetScanProgressEvent),
        **_lifecycle_events(JobKind.SERVER_AUDIT, ServerAuditProgressEvent),
        **_lifecycle_events(JobKind.SERVER_AUDIT_FIX, ServerAuditFixEvent),
        "download.started": WebSocketEventDefinition(
            "download.started", DownloadJobEvent
        ),
        "download.progress": WebSocketEventDefinition(
            "download.progress", DownloadJobEvent
        ),
        "download.completed": WebSocketEventDefinition(
            "download.completed", DownloadJobEvent
        ),
        "download.failed": WebSocketEventDefinition(
            "download.failed", DownloadJobEvent
        ),
        "download.cancelled": WebSocketEventDefinition(
            "download.cancelled", DownloadJobEvent
        ),
        "collection.theme.updated": WebSocketEventDefinition(
            "collection.theme.updated", CollectionThemeUpdatedEvent
        ),
        **_lifecycle_events(JobKind.PUBLIC_DATASET_SYNC, PublicDatasetSyncEvent),
        **_lifecycle_events(JobKind.BACKUP, BackupJobEvent),
        "library.item.upserted": WebSocketEventDefinition(
            "library.item.upserted",
            LibraryItemUpsertedEvent,
            exclude_none=False,
        ),
        "library.item.removed": WebSocketEventDefinition(
            "library.item.removed", LibraryItemRemovedEvent
        ),
        "library.items.changed": WebSocketEventDefinition(
            "library.items.changed", BulkItemOperationResult
        ),
        "public-dataset.updated": WebSocketEventDefinition(
            "public-dataset.updated",
            PublicDatasetStatus,
            exclude_none=False,
        ),
        "item.updated": WebSocketEventDefinition("item.updated", ItemUpdatedEvent),
        "job.snapshot.cleared": WebSocketEventDefinition(
            "job.snapshot.cleared", JobSnapshotClearedEvent
        ),
        "schedules.changed": WebSocketEventDefinition(
            "schedules.changed", SchedulesChangedEvent
        ),
    }
)


def validate_event_payload(event: str, payload: Any) -> dict[str, JsonValue] | None:
    """Validate a WebSocket payload against the registered schema."""
    definition = EVENT_REGISTRY.get(event)
    if definition is None:
        raise ValueError(f"Unregistered WebSocket event: {event}")
    if definition.payload_model is None:
        return None
    if isinstance(payload, definition.payload_model):
        model = payload
    else:
        model = definition.payload_model.model_validate(payload)
    return cast(
        "dict[str, JsonValue]",
        model.model_dump(
            mode="json",
            exclude_none=definition.exclude_none,
        ),
    )
