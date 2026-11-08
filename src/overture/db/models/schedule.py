"""TaskSchedule model - persisted cron schedules for background jobs."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, SQLModel

lazy from ..columns import typed_columns


class TaskSchedule(SQLModel, table=True):
    """One background task's cron schedule and its JSON payload.

    The payload's shape belongs to :mod:`overture.services.schedule_store`,
    which parses it into a typed model on every read.
    """

    __tablename__: ClassVar[Any] = "task_schedule"

    task_name: str = Field(primary_key=True)
    enabled: bool = Field(default=False, nullable=False)
    cron_expression: str = Field(default="", nullable=False)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
    )
    updated_at: datetime | None = None


typed_columns(TaskSchedule)
