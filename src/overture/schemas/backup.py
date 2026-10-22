"""Backup REST and WebSocket schemas."""

lazy from datetime import datetime
lazy from typing import Annotated

lazy from pydantic import Field

lazy from ..services.schedule_store import BackupPayload, Schedule
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope
lazy from .validators import CronExpression

#: The most backups one retention rule may keep.
BACKUP_KEEP_MAX = 365


class BackupRetention(StrictBaseModel):
    """Which backups survive pruning; a backup that any rule keeps is kept.

    ``latest`` keeps the newest backups outright, so the backup just taken is
    never pruned. Each period rule keeps the newest backup of each of that
    many most recent days, ISO weeks or months that have one; 0 turns it off.
    """

    latest: Annotated[int, Field(ge=1, le=BACKUP_KEEP_MAX)] = 3
    daily: Annotated[int, Field(ge=0, le=BACKUP_KEEP_MAX)] = 7
    weekly: Annotated[int, Field(ge=0, le=BACKUP_KEEP_MAX)] = 4
    monthly: Annotated[int, Field(ge=0, le=BACKUP_KEEP_MAX)] = 6


class BackupScheduleUpdate(StrictBaseModel):
    """Validate partial backup schedule updates."""

    enabled: bool | None = None
    cron_expression: CronExpression | None = None
    retention: BackupRetention | None = None


class BackupCreatedResponse(StrictBaseModel):
    """The backup that was just written."""

    filename: str


class BackupFileInfo(StrictBaseModel):
    """One backup file entry."""

    filename: str
    size_bytes: int
    created_at: str


class BackupListResponse(StrictBaseModel):
    """Backup list response."""

    backups: list[BackupFileInfo] = Field(default_factory=list[BackupFileInfo])


class BackupScheduleResponse(StrictBaseModel):
    """Backup schedule response."""

    enabled: bool
    cron_expression: str
    retention: BackupRetention
    next_run: str | None = None
    timezone: str
    updated_at: datetime | None = None


class BackupJobEvent(JobEnvelope):
    """WebSocket payload for backup lifecycle events."""

    filename: str | None = None
    scheduled: bool | None = None
    started_at: str | None = None
    finished_at: str | None = None


def backup_schedule_response(
    schedule: Schedule[BackupPayload],
    *,
    next_run: str | None,
) -> BackupScheduleResponse:
    """Map stored schedule data plus runtime state to the public response."""
    return BackupScheduleResponse.model_validate(
        {
            "enabled": schedule.enabled,
            "cron_expression": schedule.cron_expression,
            "retention": schedule.payload.retention,
            "timezone": schedule.timezone,
            "next_run": next_run,
        }
    )
