"""Fields shared by every named cron schedule's REST schemas."""

lazy from datetime import datetime
lazy from typing import Annotated, Literal

lazy from pydantic import AfterValidator, BaseModel, Field

lazy from ..domain import ScheduleKind
lazy from .base import StrictBaseModel
lazy from .validators import CronExpression

#: ``queued`` waits behind another schedule of its kind; ``waiting`` has
#: started but waits for a job slot or for the library gate.
type ScheduleRunStatus = Literal["idle", "queued", "waiting", "running"]


def _collapse_schedule_name(value: str) -> str:
    """Collapse internal whitespace in a user-facing schedule name."""
    name = " ".join(value.split())
    if not name:
        raise ValueError("name is required")
    return name


class ScheduleWrite[ConfigT: BaseModel](StrictBaseModel):
    """Create or update a saved schedule: its name, timing and what it runs."""

    name: Annotated[str, Field(max_length=100), AfterValidator(_collapse_schedule_name)]
    enabled: bool = True
    cron_expression: CronExpression
    config: ConfigT


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
    run_status: ScheduleRunStatus = "idle"
    waiting_for: str | None = Field(
        default=None,
        description="What a queued or waiting run is waiting for.",
    )


class SchedulesChangedEvent(StrictBaseModel):
    """WebSocket payload telling clients to reload one kind's schedules."""

    kind: ScheduleKind
