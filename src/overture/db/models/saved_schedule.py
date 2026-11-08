"""SavedSchedule model - named cron schedules for assets and sync workflows."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, Index, SQLModel, UniqueConstraint

lazy from ...domain import ScheduleKind
lazy from ..columns import enum_type, typed_columns


class SavedSchedule(SQLModel, table=True):
    """A named cron schedule for reusable asset and sync runs."""

    __tablename__: ClassVar[Any] = "saved_schedules"
    __table_args__ = (
        UniqueConstraint("kind", "name", name="uq_saved_schedules_kind_name"),
        Index("ix_saved_schedules_kind_created", "kind", "created_at", "id"),
        Index("ix_saved_schedules_enabled_kind", "enabled", "kind"),
    )

    id: int | None = Field(default=None, primary_key=True)
    kind: ScheduleKind = Field(sa_type=enum_type(ScheduleKind), index=True)
    name: str = Field(nullable=False)
    enabled: bool = Field(default=True, nullable=False, index=True)
    cron_expression: str = Field(nullable=False)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
    )
    #: Run bookkeeping a workflow carries between runs, such as a checkpoint.
    state: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
    )
    created_at: datetime = Field(nullable=False)
    updated_at: datetime = Field(nullable=False)
    last_run_at: datetime | None = None
    #: The last run's :class:`~overture.schemas.schedules.ScheduleRunSummary`.
    last_run_summary: dict[str, Any] | None = Field(default=None, sa_type=JSON)


typed_columns(SavedSchedule)
