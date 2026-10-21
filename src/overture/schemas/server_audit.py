"""Server audit REST schemas."""

lazy from enum import StrEnum
lazy from typing import Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import ArtType, ServerAsset
lazy from ..jobs.progress_log import JobOutcome
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope, MediaFolderScope
lazy from .validators import UniqueList


class ServerAuditRequest(MediaFolderScope):
    """Validate the server audit request payload."""

    art_types: UniqueList[ArtType] = Field(default_factory=lambda: list(ArtType))
    check_themes: bool = True


class ServerAuditRefreshTarget(StrictBaseModel):
    """One image refresh target selected from server audit results."""

    item_id: int
    season_id: int | None = None
    art_type: ArtType


class ServerAuditThemeDeleteTarget(StrictBaseModel):
    """One theme delete target selected from server audit results.

    Without a ``theme_id`` the server has no theme to delete, so the item is
    only refreshed to pick up the local file.
    """

    item_id: int
    server_item_id: str = Field(min_length=1)
    theme_id: str | None = None


class FixAuditRequest(StrictBaseModel):
    """Findings selected from one server audit's results, to fix in one run.

    Images are unlocked and refreshed; themes have their server theme deleted
    first, then their item is refreshed.
    """

    targets: list[ServerAuditRefreshTarget] = Field(
        default_factory=list[ServerAuditRefreshTarget]
    )
    themes: list[ServerAuditThemeDeleteTarget] = Field(
        default_factory=list[ServerAuditThemeDeleteTarget]
    )
    snapshot_finished_at: str

    @model_validator(mode="after")
    def require_a_finding(self) -> Self:
        """Reject a request that selects nothing to fix.

        Returns:
            The validated request.
        """
        if not self.targets and not self.themes:
            raise ValueError("Select at least one finding to fix")
        return self


class AuditStatus(StrEnum):
    """What an audit found when it compared one local file with the server."""

    PHASH_MATCH = "phash_match"
    PHASH_MISMATCH = "phash_mismatch"
    SERVER_MISSING = "server_missing"
    THEME_MATCH = "theme_match"
    THEME_MISMATCH = "theme_mismatch"
    THEME_SERVER_MISSING = "theme_server_missing"
    THEME_UNKNOWN = "theme_unknown"
    LOCAL_MISSING = "local_missing"
    UNRESOLVED_SERVER_ID = "unresolved_server_id"
    ERROR = "error"

    @property
    def outcome(self) -> JobOutcome:
        """Return the outcome the audit's progress log reports for this finding."""
        return _AUDIT_OUTCOMES[self]

    @property
    def matched(self) -> bool:
        """Whether the server shows exactly the local file, so nothing needs fixing."""
        return self.outcome is JobOutcome.MATCHED


_AUDIT_OUTCOMES: frozendict[AuditStatus, JobOutcome] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        AuditStatus.PHASH_MATCH: JobOutcome.MATCHED,
        AuditStatus.THEME_MATCH: JobOutcome.MATCHED,
        AuditStatus.PHASH_MISMATCH: JobOutcome.MISMATCH,
        AuditStatus.THEME_MISMATCH: JobOutcome.MISMATCH,
        AuditStatus.SERVER_MISSING: JobOutcome.MISMATCH,
        AuditStatus.THEME_SERVER_MISSING: JobOutcome.MISMATCH,
        AuditStatus.LOCAL_MISSING: JobOutcome.SKIPPED,
        AuditStatus.UNRESOLVED_SERVER_ID: JobOutcome.SKIPPED,
        AuditStatus.THEME_UNKNOWN: JobOutcome.SKIPPED,
        AuditStatus.ERROR: JobOutcome.ERROR,
    }
)


class ServerAuditResult(StrictBaseModel):
    """One server audit result row sent over WebSocket."""

    kind: Literal["art", "theme"]
    item_id: int
    season_id: int | None = None
    art_type: ServerAsset
    status: AuditStatus
    title: str
    local_path: str | None = None
    server_image_present: bool | None = None
    hamming: int | None = None
    reason: str | None = None
    local_duration: float | None = None
    server_duration: float | None = None
    server_item_id: str | None = None
    theme_id: str | None = None
    theme_title: str | None = None
    refreshed: bool | None = Field(
        default=None,
        description="A fix ran and the media server now matches the local file.",
    )
    refresh_error: str | None = Field(
        default=None,
        description="Why the last fix failed, or how the server still differs.",
    )


class ServerAuditProgressEvent(JobEnvelope):
    """WebSocket payload for server audit lifecycle events."""

    results_total: int | None = None
    done: int | None = None
    total: int | None = None
    results_found: int | None = None
    errors: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    results: list[ServerAuditResult] | None = None


class ServerAuditFixEvent(JobEnvelope):
    """WebSocket payload for the job that fixes audit findings and checks them.

    ``done`` counts the fixed files that have settled: ``verified`` once the
    server matches the local file again, ``unchanged`` when it still differs
    after the server stopped picking up changes, ``errors`` when the fix itself
    failed.
    """

    done: int | None = None
    total: int | None = None
    verified: int | None = None
    unchanged: int | None = None
    errors: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
