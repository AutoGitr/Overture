"""TaskSchedule model - persisted cron schedules for background jobs."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, SQLModel


class TaskScheduleBase(SQLModel):
    """Base model holding background task schedule fields."""

    enabled: bool = Field(default=False, nullable=False)
    cron_expression: str = Field(default="", nullable=False)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
        sa_column_kwargs={"name": "payload_json"},
    )
    updated_at: datetime | None = None


class TaskSchedule(TaskScheduleBase, table=True):
    """Store one background task's cron schedule and its JSON payload.

    The payload's shape belongs to :mod:`overture.services.schedule_store`,
    which parses it into a typed model on every read.
    """

    __tablename__: ClassVar[Any] = "task_schedule"

    task_name: str = Field(primary_key=True)
