"""Every kind of job Overture runs, and the lifecycle each one publishes."""

lazy from enum import StrEnum


class JobKind(StrEnum):
    """One kind of job; its value names it in events and persisted results."""

    SYNC = "sync"
    BULK_ART = "bulk_art"
    BULK_THEME = "bulk_theme"
    ASSET_SCAN = "asset_scan"
    SERVER_AUDIT = "server_audit"
    SERVER_AUDIT_FIX = "server_audit_fix"
    PUBLIC_DATASET_SYNC = "public_dataset_sync"
    BACKUP = "backup"
    DOWNLOAD = "download"

    @property
    def event_prefix(self) -> str:
        """Return the prefix of this kind's WebSocket lifecycle events."""
        return _EVENT_PREFIXES[self]

    @property
    def label(self) -> str:
        """Return how a run of this kind is named in logs."""
        return _LABELS[self]

    @property
    def clearable(self) -> bool:
        """Whether a client may clear this kind's last result from its view."""
        return self in _CLEARABLE


_EVENT_PREFIXES = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        JobKind.SYNC: "sync",
        JobKind.BULK_ART: "match",
        JobKind.BULK_THEME: "theme",
        JobKind.ASSET_SCAN: "assets.scan",
        JobKind.SERVER_AUDIT: "server.audit",
        JobKind.SERVER_AUDIT_FIX: "server.audit.fix",
        JobKind.PUBLIC_DATASET_SYNC: "public-dataset.sync",
        JobKind.BACKUP: "backup",
        JobKind.DOWNLOAD: "download",
    }
)
_LABELS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        JobKind.SYNC: "library sync",
        JobKind.BULK_ART: "bulk art match",
        JobKind.BULK_THEME: "bulk theme match",
        JobKind.ASSET_SCAN: "asset scan",
        JobKind.SERVER_AUDIT: "server audit",
        JobKind.SERVER_AUDIT_FIX: "server audit fix",
        JobKind.PUBLIC_DATASET_SYNC: "OvertureDB sync",
        JobKind.BACKUP: "backup",
        JobKind.DOWNLOAD: "download",
    }
)
_CLEARABLE = frozenset(
    {
        JobKind.SYNC,
        JobKind.BULK_ART,
        JobKind.BULK_THEME,
        JobKind.ASSET_SCAN,
        JobKind.SERVER_AUDIT,
    }
)


class LifecycleStatus(StrEnum):
    """One step of a run's lifecycle, as its events name it."""

    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def running(self) -> bool:
        """Whether the run is still going after this step."""
        return self in {LifecycleStatus.STARTED, LifecycleStatus.PROGRESS}

    @property
    def terminal(self) -> bool:
        """Whether this step ends the run."""
        return not self.running


class DownloadStatus(StrEnum):
    """One step of a queued download, as its events name it."""

    PENDING = "pending"
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def running(self) -> bool:
        """Whether the download is being fetched or written."""
        return self in {DownloadStatus.STARTED, DownloadStatus.PROGRESS}
