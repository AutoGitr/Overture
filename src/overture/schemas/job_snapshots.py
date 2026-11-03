"""Result snapshot REST and WebSocket schemas."""

lazy from typing import Literal

lazy from pydantic import Field

lazy from ..jobs.kinds import JobKind
lazy from ..jobs.progress_log import JobLogEntry
lazy from ..utils.types import JsonValue
lazy from .base import StrictBaseModel


class JobResults(StrictBaseModel):
    """Every finding of one retained scan or audit run, in the order found."""

    run_id: str
    items: list[dict[str, JsonValue]]


class JobLogPage(StrictBaseModel):
    """One ordered page of a run's progress log."""

    run_id: str
    total: int = Field(description="Lines the page's filter matches.")
    offset: int
    items: list[JobLogEntry]


class JobSnapshotClearResponse(StrictBaseModel):
    """Describe the outcome of a guarded snapshot clear request."""

    status: Literal["cleared", "stale", "empty"]
    kind: JobKind
    finished_at: str


class JobSnapshotClearedEvent(StrictBaseModel):
    """Notify clients that a terminal popup snapshot was cleared."""

    kind: JobKind
    finished_at: str
