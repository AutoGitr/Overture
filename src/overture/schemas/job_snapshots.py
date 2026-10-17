"""Result snapshot REST and WebSocket schemas."""

lazy from typing import Literal

lazy from ..jobs.kinds import JobKind
lazy from ..utils.types import JsonValue
lazy from .base import StrictBaseModel


class JobResultsPage(StrictBaseModel):
    """One ordered page of persisted scan, audit, or artwork findings."""

    run_id: str
    total: int
    offset: int
    items: list[dict[str, JsonValue]]


class JobSnapshotClearResponse(StrictBaseModel):
    """Describe the outcome of a guarded snapshot clear request."""

    status: Literal["cleared", "stale", "empty"]
    kind: JobKind
    finished_at: str


class JobSnapshotClearedEvent(StrictBaseModel):
    """Notify clients that a terminal popup snapshot was cleared."""

    kind: JobKind
    finished_at: str
