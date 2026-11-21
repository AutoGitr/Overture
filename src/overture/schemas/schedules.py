"""Fields shared by every named cron schedule's REST schemas."""

lazy from datetime import datetime
lazy from typing import Literal

lazy from pydantic import BaseModel, Field

lazy from ..domain import NamedScheduleKind
lazy from .base import StrictBaseModel
lazy from .validators import CronExpression, DisplayName

#: ``queued`` waits behind another schedule of its kind; ``waiting`` has
#: started but waits for a job slot or for the library gate.
type ScheduleRunStatus = Literal["idle", "queued", "waiting", "running"]


class ScheduleWrite[ConfigT: BaseModel](StrictBaseModel):
    """Create or update a saved schedule: its name, timing and what it runs."""

    name: DisplayName
    enabled: bool = True
    cron_expression: CronExpression
    config: ConfigT


class ScheduleRunSummary(StrictBaseModel):
    """What a schedule's last run did: how long it took and what it counted."""

    duration_seconds: float | None = None
    #: Counter names and values in the order they are shown; zeros are left out.
    counts: dict[str, int] = Field(default_factory=dict[str, int])
    failed: bool = False


class ScheduleResponseBase(StrictBaseModel):
    """Saved schedule fields shared by every schedule kind."""

    id: int
    name: str
    enabled: bool
    cron_expression: str
    timezone: str
    next_run: str | None = None
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None = None
    last_run: ScheduleRunSummary | None = None
    run_status: ScheduleRunStatus = "idle"
    waiting_for: str | None = Field(
        default=None,
        description="What a queued or waiting run is waiting for.",
    )


class SchedulesChangedEvent(StrictBaseModel):
    """WebSocket payload telling clients to reload one kind's schedules."""

    kind: NamedScheduleKind
