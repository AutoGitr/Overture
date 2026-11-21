"""Typed WebSocket event registry and payload validation."""

lazy from dataclasses import dataclass
lazy from typing import Any, cast

lazy from pydantic import BaseModel

lazy from ..jobs.kinds import JobKind, LifecycleStatus
lazy from ..schemas.asset_manager import AssetScanProgressEvent
lazy from ..schemas.backup import BackupJobEvent
lazy from ..schemas.bulk import BulkArtJobEvent, BulkThemeJobEvent
lazy from ..schemas.catalog import CatalogStatus, CatalogSyncEvent
lazy from ..schemas.collections import (
    CollectionMonitoredEvent,
    CollectionUpdatedEvent,
)
lazy from ..schemas.common import JsonValue
lazy from ..schemas.downloads import DownloadJobEvent
lazy from ..schemas.job_snapshots import JobSnapshotClearedEvent
lazy from ..schemas.library import (
    BulkItemOperationResult,
    ItemUpdatedEvent,
    LibraryItemRemovedEvent,
    LibraryItemUpsertedEvent,
)
lazy from ..schemas.media_server import MediaServerStatus
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
            "realtime.snapshot", RealtimeSnapshot
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
        "collections.changed": WebSocketEventDefinition("collections.changed", None),
        "collection.updated": WebSocketEventDefinition(
            "collection.updated", CollectionUpdatedEvent
        ),
        "collection.monitored": WebSocketEventDefinition(
            "collection.monitored", CollectionMonitoredEvent
        ),
        **_lifecycle_events(JobKind.CATALOG_SYNC, CatalogSyncEvent),
        **_lifecycle_events(JobKind.BACKUP, BackupJobEvent),
        "library.item.upserted": WebSocketEventDefinition(
            "library.item.upserted", LibraryItemUpsertedEvent
        ),
        "library.item.removed": WebSocketEventDefinition(
            "library.item.removed", LibraryItemRemovedEvent
        ),
        "library.items.changed": WebSocketEventDefinition(
            "library.items.changed", BulkItemOperationResult
        ),
        "catalog.updated": WebSocketEventDefinition("catalog.updated", CatalogStatus),
        "item.updated": WebSocketEventDefinition("item.updated", ItemUpdatedEvent),
        "job.snapshot.cleared": WebSocketEventDefinition(
            "job.snapshot.cleared", JobSnapshotClearedEvent
        ),
        "schedules.changed": WebSocketEventDefinition(
            "schedules.changed", SchedulesChangedEvent
        ),
        "media-server.status": WebSocketEventDefinition(
            "media-server.status", MediaServerStatus
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
    # Every field is sent, null or not: the generated types name them all.
    return cast("dict[str, JsonValue]", model.model_dump(mode="json"))
