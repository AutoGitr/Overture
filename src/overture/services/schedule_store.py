"""Typed persistence for singleton cron-backed background schedules.

Each singleton schedule (backup, catalog) is stored as a row in
``saved_schedules`` keyed by its :class:`~overture.domain.ScheduleKind` plus a
typed JSON payload. The payload's shape is a Pydantic model rather than a
free-form dict, so defaults, ranges, and field names are declared once and
enforced on the way in and out.
"""

lazy from dataclasses import dataclass
lazy from datetime import datetime

lazy from pydantic import BaseModel, Field
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.saved_schedule import SavedSchedule
lazy from ..domain import ScheduleKind
lazy from ..repositories.saved_schedules import SavedScheduleRepository
lazy from ..schemas.backup import BackupRetention
lazy from ..schemas.catalog import (
    CatalogSyncOutcome,
    CatalogSyncStats,
)
lazy from ..utils.time import utc_now

DEFAULT_BACKUP_CRON = "0 3 * * *"
DEFAULT_CATALOG_CRON = "0 0 * * *"


class SchedulePayload(BaseModel):
    """Base for the JSON payload stored alongside a schedule."""


class BackupPayload(SchedulePayload):
    """Settings for scheduled database backups."""

    retention: BackupRetention = Field(default_factory=BackupRetention)


class CatalogPayload(SchedulePayload):
    """Settings and last-run bookkeeping for the OvertureDB catalog sync."""

    last_synced_at: datetime | None = None
    last_status: CatalogSyncOutcome = "never_synced"
    last_stats: CatalogSyncStats | None = None


@dataclass(slots=True, frozen=True)
class ScheduleSpec[PayloadT: SchedulePayload]:
    """Static description of one singleton persisted schedule."""

    kind: ScheduleKind
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


BACKUP_SCHEDULE = ScheduleSpec(
    ScheduleKind.BACKUP, BackupPayload, DEFAULT_BACKUP_CRON, default_enabled=True
)
CATALOG_SCHEDULE = ScheduleSpec(
    ScheduleKind.CATALOG,
    CatalogPayload,
    DEFAULT_CATALOG_CRON,
    default_enabled=True,
)


def _parse[PayloadT: SchedulePayload](
    record: SavedSchedule, spec: ScheduleSpec[PayloadT]
) -> PayloadT:
    """Return the record's payload as its declared model, defaults filled in."""
    return spec.payload_model.model_validate(record.payload or {})


async def _record[PayloadT: SchedulePayload](
    session: AsyncSession, spec: ScheduleSpec[PayloadT]
) -> SavedSchedule:
    """Return the schedule row to write to, creating it the first time."""
    repo = SavedScheduleRepository(session)
    record = await repo.singleton(spec.kind)
    if record is None:
        now = utc_now()
        record = SavedSchedule(
            kind=spec.kind,
            name=spec.kind.value,
            enabled=spec.default_enabled,
            cron_expression=spec.default_cron,
            payload=spec.payload_model().model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        repo.add(record)
        await session.flush()
    return record


async def catalog_enabled(session: AsyncSession) -> bool:
    """Return whether OvertureDB catalog integration is enabled."""
    return await SavedScheduleRepository(session).enabled(
        ScheduleKind.CATALOG, default=CATALOG_SCHEDULE.default_enabled
    )


async def load_schedule[PayloadT: SchedulePayload](
    session: AsyncSession,
    spec: ScheduleSpec[PayloadT],
    *,
    timezone: str = "UTC",
) -> Schedule[PayloadT]:
    """Return one schedule, falling back to the spec's defaults when unsaved.

    Reading does not write. A schedule nobody has saved yet simply reads as
    its defaults; inventing a row here would mean every status endpoint and
    every scheduled run opened a write transaction to answer a question.
    """
    record = await SavedScheduleRepository(session).singleton(spec.kind)
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
    SavedScheduleRepository(session).add(record)
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
