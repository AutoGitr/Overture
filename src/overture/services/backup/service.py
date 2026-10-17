"""Manual and scheduled backups with shared storage and lifecycle events."""

lazy import logging
lazy import sqlite3

lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...config import Settings
lazy from ...db.session import Database
lazy from ...schemas.backup import (
    BackupCreatedResponse,
    BackupListResponse,
    BackupScheduleResponse,
    BackupScheduleUpdate,
    backup_schedule_response,
)
lazy from ...utils.errors import PublicServiceError, public_error_message
lazy from ...utils.time import utc_now_iso
lazy from ..retention import run_retention_pass
lazy from ..schedule_store import (
    BACKUP_SCHEDULE,
    BackupPayload,
    load_schedule,
    save_schedule,
)
lazy from ..scheduler import ScheduledJobInfo, SchedulerService
lazy from .events import BackupEvents
lazy from .files import BackupInProgressError, BackupStore

logger = logging.getLogger(__name__)

#: The scheduler job that takes the automatic backups.
_SCHEDULED_BACKUP_JOB = "auto_backup"
#: Errors a backup reports instead of crashing its caller.
_BACKUP_ERRORS = (SQLAlchemyError, OSError, RuntimeError, sqlite3.Error, ValueError)


class BackupService:
    """Own manual backups, scheduled backups, and their saved schedule."""

    def __init__(
        self,
        *,
        scheduler: SchedulerService,
        events: BackupEvents,
        store: BackupStore,
        app_config: Settings,
        database: Database,
    ) -> None:
        self._app_config = app_config
        self._database = database
        self.scheduler = scheduler
        self.events = events
        self.store = store

    async def _backup(self, *, scheduled: bool) -> str:
        """Write one backup, announcing it as it goes; return its file name.

        Raises:
            BackupInProgressError: When a manual backup finds one running.
        """
        started_at: str | None = None
        try:
            async with self._database.read_session() as session:
                schedule = await load_schedule(
                    session, BACKUP_SCHEDULE, timezone=self._app_config.TZ
                )
            started_at = utc_now_iso()
            await self.events.publish(
                "started", scheduled=scheduled, started_at=started_at
            )
            filename = await self.store.create(
                retention=schedule.payload.retention, reject_if_busy=not scheduled
            )
        except _BACKUP_ERRORS as exc:
            await self.events.publish(
                "failed",
                scheduled=scheduled,
                started_at=started_at,
                error=public_error_message(exc),
                snapshot=True,
            )
            raise
        await self.events.publish(
            "completed",
            scheduled=scheduled,
            started_at=started_at,
            filename=filename,
            snapshot=True,
        )
        return filename

    async def backup_now(self) -> BackupCreatedResponse:
        """Back the database up now, refusing to queue behind a running backup."""
        try:
            filename = await self._backup(scheduled=False)
        except _BACKUP_ERRORS as exc:
            status_code = 409 if isinstance(exc, BackupInProgressError) else 500
            raise PublicServiceError(status_code, public_error_message(exc)) from exc
        return BackupCreatedResponse(filename=filename)

    async def backup_before_upgrade(self) -> None:
        """Keep the previous schema restorable; the next scheduled backup prunes."""
        filename = await self.store.create(retention=None)
        logger.info("Backed up the database before upgrading it: %s", filename)

    def list_backups(self) -> BackupListResponse:
        """Return all existing backups, newest first."""
        return BackupListResponse(backups=self.store.list_backups())

    async def get_schedule(self) -> BackupScheduleResponse:
        """Return the current backup schedule configuration."""
        async with self._database.read_session() as session:
            schedule = await load_schedule(
                session, BACKUP_SCHEDULE, timezone=self._app_config.TZ
            )
        runtime = self.get_schedule_info()
        return backup_schedule_response(schedule, next_run=runtime.next_run)

    async def update_schedule(
        self,
        body: BackupScheduleUpdate,
    ) -> BackupScheduleResponse:
        """Update the backup schedule configuration."""
        async with self._database.write_session() as session:
            updated = await save_schedule(
                session,
                BACKUP_SCHEDULE,
                enabled=body.enabled,
                cron_expression=body.cron_expression,
                payload=(
                    BackupPayload(retention=body.retention)
                    if body.retention is not None
                    else None
                ),
                timezone=self._app_config.TZ,
            )
        self._schedule_job(
            enabled=updated.enabled, cron_expression=updated.cron_expression
        )
        runtime = self.get_schedule_info()
        return backup_schedule_response(updated, next_run=runtime.next_run)

    async def start(self) -> None:
        """Start the backup scheduler."""
        async with self._database.read_session() as session:
            schedule = await load_schedule(
                session, BACKUP_SCHEDULE, timezone=self._app_config.TZ
            )

        self._schedule_job(
            enabled=schedule.enabled,
            cron_expression=schedule.cron_expression,
        )
        self.scheduler.set_interval_job(
            "retention",
            enabled=True,
            func=self._run_retention,
            minutes=24 * 60,
        )
        logger.debug("Backup scheduler started")

    async def _run_retention(self) -> None:
        await run_retention_pass(database=self._database)

    async def stop(self) -> None:
        """Stop the backup scheduler."""
        await self.store.close()
        logger.debug("Backup scheduler stopped")

    def _schedule_job(self, *, enabled: bool, cron_expression: str) -> None:
        """Schedule or remove the background job."""
        if self.scheduler.set_cron_job(
            _SCHEDULED_BACKUP_JOB,
            enabled=enabled,
            func=self._run_scheduled_backup,
            cron_expression=cron_expression,
        ):
            logger.info("Automatic backups scheduled (%s)", cron_expression)
        else:
            logger.info("Automatic backups disabled")

    async def _run_scheduled_backup(self) -> None:
        """Take a scheduled backup; its failure is announced, not raised."""
        try:
            await self._backup(scheduled=True)
        except _BACKUP_ERRORS:
            logger.debug("The scheduled backup failed", exc_info=True)

    def get_schedule_info(self) -> ScheduledJobInfo:
        """Return schedule info."""
        return self.scheduler.job_info(_SCHEDULED_BACKUP_JOB, include_trigger=True)
