"""Typed persistence for the cron-backed background schedules.

Every schedule is one row in ``task_schedule`` plus a JSON payload. The
payload's shape is a Pydantic model rather than a free-form dict, so defaults,
ranges, and field names are declared once and enforced on the way in and out.
Adding a schedule means adding a payload model and a :class:`ScheduleSpec`.
"""

lazy from dataclasses import dataclass
lazy from datetime import datetime

lazy from pydantic import BaseModel, Field
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.schedule import TaskSchedule
lazy from ..schemas.backup import BackupRetention
lazy from ..schemas.public_dataset import (
    PublicDatasetSyncOutcome,
    PublicDatasetSyncStats,
)
lazy from ..utils.time import utc_now

SYNC_SERVER_TASK_NAME = "sync_server"
BACKUP_TASK_NAME = "backup"
PUBLIC_DATASET_TASK_NAME = "public_dataset"

DEFAULT_BACKUP_CRON = "0 3 * * *"
DEFAULT_PUBLIC_DATASET_CRON = "0 0 * * *"


class SchedulePayload(BaseModel):
    """Base for the JSON payload stored alongside a schedule."""


class SyncServerPayload(SchedulePayload):
    """The media server the saved sync schedules were written against.

    This entry never runs: it has no cron. Named sync schedules carry library
    IDs and checkpoints that only mean something on the server that issued
    them, so sync remembers that server here to notice a switch.
    """

    last_media_server: str | None = None


class BackupPayload(SchedulePayload):
    """Settings for scheduled database backups."""

    retention: BackupRetention = Field(default_factory=BackupRetention)


class PublicDatasetPayload(SchedulePayload):
    """Settings and last-run bookkeeping for the OvertureDB catalog sync."""

    last_synced_at: datetime | None = None
    last_status: PublicDatasetSyncOutcome = "never_synced"
    last_stats: PublicDatasetSyncStats | None = None


@dataclass(slots=True, frozen=True)
class ScheduleSpec[PayloadT: SchedulePayload]:
    """Static description of one persisted schedule."""

    task_name: str
    payload_model: type[PayloadT]
    default_cron: str = ""
    default_enabled: bool = False


@dataclass(slots=True, frozen=True)
class Schedule[PayloadT: SchedulePayload]:
    """One schedule as callers see it."""

    enabled: bool
    cron_expression: str
    payload: PayloadT
    updated_at: datetime | None

    timezone: str = "UTC"


SYNC_SERVER_SCHEDULE = ScheduleSpec(SYNC_SERVER_TASK_NAME, SyncServerPayload)
BACKUP_SCHEDULE = ScheduleSpec(
    BACKUP_TASK_NAME, BackupPayload, DEFAULT_BACKUP_CRON, default_enabled=True
)
PUBLIC_DATASET_SCHEDULE = ScheduleSpec(
    PUBLIC_DATASET_TASK_NAME, PublicDatasetPayload, DEFAULT_PUBLIC_DATASET_CRON
)


def _parse[PayloadT: SchedulePayload](
    record: TaskSchedule, spec: ScheduleSpec[PayloadT]
) -> PayloadT:
    """Return the record's payload as its declared model, defaults filled in."""
    return spec.payload_model.model_validate(record.payload or {})


async def _record[PayloadT: SchedulePayload](
    session: AsyncSession, spec: ScheduleSpec[PayloadT]
) -> TaskSchedule:
    """Return the schedule row to write to, creating it the first time."""
    record = await session.get(TaskSchedule, spec.task_name)
    if record is None:
        record = TaskSchedule(
            task_name=spec.task_name,
            enabled=spec.default_enabled,
            cron_expression=spec.default_cron,
            payload=spec.payload_model().model_dump(mode="json"),
            updated_at=utc_now(),
        )
        session.add(record)
        await session.flush()
    return record


async def load_schedule[PayloadT: SchedulePayload](
    session: AsyncSession,
    spec: ScheduleSpec[PayloadT],
    *,
    timezone: str = "UTC",
) -> Schedule[PayloadT]:
    """Return one schedule, falling back to the spec's defaults when unsaved.

    Reading does not write. A schedule nobody has saved yet simply reads as
    its defaults; inventing a row here would mean every status endpoint and
    every scheduled run opened a write transaction to answer a question, and
    that is what put a dozen read-only callers on ``write_session``.
    """
    record = await session.get(TaskSchedule, spec.task_name)
    if record is None:
        return Schedule(
            enabled=spec.default_enabled,
            cron_expression=spec.default_cron,
            payload=spec.payload_model(),
            updated_at=None,
            timezone=timezone,
        )
    return Schedule(
        enabled=bool(record.enabled),
        cron_expression=record.cron_expression or spec.default_cron,
        payload=_parse(record, spec),
        updated_at=record.updated_at,
        timezone=timezone,
    )


async def save_schedule[PayloadT: SchedulePayload](
    session: AsyncSession,
    spec: ScheduleSpec[PayloadT],
    *,
    enabled: bool | None = None,
    cron_expression: str | None = None,
    payload: PayloadT | None = None,
    timezone: str = "UTC",
) -> Schedule[PayloadT]:
    """Persist the supplied parts of one schedule and return the new state.

    *cron_expression* is already validated: requests carry it as a
    :data:`~overture.schemas.validators.CronExpression`.
    """
    record = await _record(session, spec)
    if enabled is not None:
        record.enabled = enabled
    if cron_expression is not None:
        record.cron_expression = cron_expression
    if payload is not None:
        record.payload = payload.model_dump(mode="json")
    record.updated_at = utc_now()
    session.add(record)
    return await load_schedule(session, spec, timezone=timezone)


async def patch_payload[PayloadT: SchedulePayload](
    session: AsyncSession,
    spec: ScheduleSpec[PayloadT],
    *,
    timezone: str = "UTC",
    **changes: object,
) -> Schedule[PayloadT]:
    """Persist a partial payload update, leaving the other fields alone.

    Raises:
        ValueError: When a change names no field of the payload, or holds a
            value it does not accept.
    """
    if unknown := set(changes) - set(spec.payload_model.model_fields):
        raise ValueError(f"Unknown schedule payload fields: {sorted(unknown)}")
    current = await load_schedule(session, spec, timezone=timezone)
    return await save_schedule(
        session,
        spec,
        payload=spec.payload_model.model_validate(
            {**current.payload.model_dump(), **changes}
        ),
        timezone=timezone,
    )
