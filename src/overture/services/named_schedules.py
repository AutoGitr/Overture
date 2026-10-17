"""Named cron schedules of one kind: persistence, cron registration, and runs.

Assets and sync both let users save any number of named schedules. Each kind
owns one :class:`NamedSchedules`, which stores the rows, registers their cron
jobs, and runs due schedules one at a time on its own queue. What a run does
is the kind's business, supplied as a callback.

Every change a client would show - a saved edit, a run queued, waiting,
running or finished - is announced as ``schedules.changed`` so open schedule
lists reload instead of going stale.
"""

lazy import asyncio
lazy import contextlib
lazy import logging
lazy from collections.abc import Awaitable, Callable
lazy from dataclasses import dataclass
lazy from datetime import datetime
lazy from typing import Any

lazy from pydantic import BaseModel

lazy from .. import protocols
lazy from ..config import Settings
lazy from ..db.models.saved_schedule import SavedSchedule
lazy from ..db.session import Database
lazy from ..domain import ScheduleKind
lazy from ..jobs.gate import WaitReporter
lazy from ..repositories.saved_schedules import SavedScheduleRepository
lazy from ..schemas.common import Status, StatusResponse
lazy from ..schemas.schedules import ScheduleRunStatus, ScheduleWrite
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.time import utc_now
lazy from .scheduler import SchedulerService

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class NamedSchedule[ConfigT: BaseModel]:
    """One saved schedule, detached from its database session."""

    id: int
    kind: ScheduleKind
    name: str
    enabled: bool
    cron_expression: str
    timezone: str
    next_run: str | None
    config: ConfigT
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    run_status: ScheduleRunStatus
    waiting_for: str | None


#: Runs one schedule to completion and returns its new state, or ``None`` to
#: keep the state it had. The reporter is told what the run waits for, and
#: ``None`` once it runs.
type ScheduleRunner[ConfigT: BaseModel] = Callable[
    [NamedSchedule[ConfigT], WaitReporter], Awaitable[dict[str, Any] | None]
]


@dataclass(slots=True, frozen=True)
class _ActiveRun:
    schedule_id: int
    name: str
    waiting_for: str | None = None


@dataclass(slots=True, frozen=True)
class _QueuedRun:
    schedule_id: int
    force: bool


class NamedSchedules[ConfigT: BaseModel, ResponseT: BaseModel]:
    """Saved schedules of one kind, their cron jobs, and their queued runs."""

    def __init__(
        self,
        kind: ScheduleKind,
        *,
        config_model: type[ConfigT],
        response_model: type[ResponseT],
        run: ScheduleRunner[ConfigT],
        scheduler: SchedulerService,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        database: Database,
    ) -> None:
        self.kind = kind
        self._config_model = config_model
        self._response_model = response_model
        self._run = run
        self.scheduler = scheduler
        self._app_config = app_config
        self._database = database
        self._publisher = publisher
        self._queue: asyncio.Queue[_QueuedRun] = asyncio.Queue()
        self._pending: set[int] = set()
        self._active: _ActiveRun | None = None
        self._worker: asyncio.Task[None] | None = None
        self._announcements: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def healthy(self) -> bool:
        """Return whether queued runs are still being processed."""
        return self._worker is not None and not self._worker.done() and not self._closed

    async def start(self) -> None:
        """Start the queue worker and register every saved schedule."""
        self._ensure_worker()
        async with self._database.read_session() as session:
            records = await SavedScheduleRepository(session).of_kind(self.kind)
            registrations = [
                (record.id, bool(record.enabled), record.cron_expression)
                for record in records
                if record.id is not None
            ]
        for schedule_id, enabled, cron_expression in registrations:
            self._register(
                schedule_id, enabled=enabled, cron_expression=cron_expression
            )
        logger.debug("%s schedules started", self.kind.capitalize())

    async def stop(self) -> None:
        """Stop the queue worker; a run in progress is cancelled."""
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        await asyncio.gather(*self._announcements, return_exceptions=True)
        logger.debug("%s schedules stopped", self.kind.capitalize())

    async def wait_for_pending_runs(self) -> None:
        """Wait until every queued run has finished processing."""
        await self._queue.join()

    async def all(self) -> list[ResponseT]:
        """Return every saved schedule of this kind."""
        async with self._database.read_session() as session:
            records = await SavedScheduleRepository(session).of_kind(self.kind)
            return [self._response(record) for record in records]

    async def create(self, fields: ScheduleWrite[ConfigT]) -> ResponseT:
        """Save a new schedule and register its cron job."""
        async with self._database.write_session() as session:
            repository = SavedScheduleRepository(session)
            await self._ensure_unique_name(repository, fields.name)
            now = utc_now()
            record = SavedSchedule(
                kind=self.kind,
                name=fields.name,
                enabled=fields.enabled,
                cron_expression=fields.cron_expression,
                payload=fields.config.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            repository.add(record)
            await session.flush()
            return self._saved(record)

    async def update(
        self, schedule_id: int, fields: ScheduleWrite[ConfigT]
    ) -> ResponseT:
        """Replace a schedule's settings, keeping its run state."""
        async with self._database.write_session() as session:
            repository = SavedScheduleRepository(session)
            record = await self._get(repository, schedule_id)
            await self._ensure_unique_name(
                repository, fields.name, exclude_id=schedule_id
            )
            record.sqlmodel_update(
                {
                    "name": fields.name,
                    "enabled": fields.enabled,
                    "cron_expression": fields.cron_expression,
                    "payload": fields.config.model_dump(mode="json"),
                    "updated_at": utc_now(),
                }
            )
            session.add(record)
            await session.flush()
            return self._saved(record)

    async def delete(self, schedule_id: int) -> StatusResponse:
        """Delete a schedule and its cron job."""
        async with self._database.write_session() as session:
            repository = SavedScheduleRepository(session)
            await repository.delete(await self._get(repository, schedule_id))
        self.scheduler.remove_job(_job_id(schedule_id))
        self._announce()
        return StatusResponse(status=Status.DELETED)

    async def run_now(self, schedule_id: int) -> StatusResponse:
        """Queue a schedule for immediate execution, even when disabled."""
        async with self._database.read_session() as session:
            await self._get(SavedScheduleRepository(session), schedule_id)
        self._ensure_worker()
        self._enqueue(schedule_id, force=True)
        return StatusResponse(status=Status.QUEUED)

    async def reset(self, rewrite: Callable[[ConfigT], ConfigT]) -> None:
        """Rewrite every schedule's settings and clear its run state."""
        async with self._database.write_session() as session:
            for record in await SavedScheduleRepository(session).of_kind(self.kind):
                config = self._config_model.model_validate(record.payload)
                record.payload = rewrite(config).model_dump(mode="json")
                record.state = {}
                record.updated_at = utc_now()
                session.add(record)
        self._announce()

    def _saved(self, record: SavedSchedule) -> ResponseT:
        if record.id is not None:
            self._register(
                record.id,
                enabled=bool(record.enabled),
                cron_expression=record.cron_expression,
            )
        self._announce()
        return self._response(record)

    def _register(
        self, schedule_id: int, *, enabled: bool, cron_expression: str
    ) -> None:
        async def enqueue() -> None:
            self._enqueue(schedule_id, force=False)

        if self.scheduler.set_cron_job(
            _job_id(schedule_id),
            enabled=enabled,
            func=enqueue,
            cron_expression=cron_expression,
        ):
            logger.info(
                "%s schedule %s scheduled (%s)",
                self.kind.capitalize(),
                schedule_id,
                cron_expression,
            )
        else:
            logger.info("%s schedule %s disabled", self.kind.capitalize(), schedule_id)

    async def _get(
        self, repository: SavedScheduleRepository, schedule_id: int
    ) -> SavedSchedule:
        record = await repository.get(schedule_id)
        if record is None or record.kind != self.kind:
            raise PublicServiceError(404, "Schedule not found")
        return record

    async def _ensure_unique_name(
        self,
        repository: SavedScheduleRepository,
        name: str,
        *,
        exclude_id: int | None = None,
    ) -> None:
        if await repository.name_exists(
            kind=self.kind, name=name, exclude_id=exclude_id
        ):
            raise PublicServiceError(400, "A schedule with this name already exists")

    def _enqueue(self, schedule_id: int, *, force: bool) -> None:
        if self._closed:
            raise RuntimeError(f"{self.kind.capitalize()} schedules are stopping")
        if schedule_id not in self._pending:
            self._pending.add(schedule_id)
            self._queue.put_nowait(_QueuedRun(schedule_id, force))
            self._announce()

    def _announce(self) -> None:
        """Tell clients this kind's schedules changed, without waiting on them."""
        task = asyncio.create_task(
            self._publisher.broadcast("schedules.changed", {"kind": self.kind})
        )
        self._announcements.add(task)
        task.add_done_callback(self._announced)

    def _announced(self, task: asyncio.Task[None]) -> None:
        self._announcements.discard(task)
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.warning(
                "Could not announce %s schedule change: %s", self.kind, failure
            )

    def _report(self, waiting_for: str | None) -> None:
        """Record what the active run waits for; ``None`` means it runs."""
        active = self._active
        if active is not None and active.waiting_for != waiting_for:
            self._active = _ActiveRun(active.schedule_id, active.name, waiting_for)
            self._announce()

    def _ensure_worker(self) -> None:
        if self._closed:
            raise RuntimeError(f"{self.kind.capitalize()} schedules are stopping")
        if self._worker is None:
            self._worker = asyncio.create_task(self._worker_loop())
            self._worker.add_done_callback(self._worker_done)
        elif self._worker.done():
            raise RuntimeError(f"{self.kind.capitalize()} schedule worker unavailable")

    def _worker_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.error("The %s schedule worker failed", self.kind, exc_info=failure)

    async def _worker_loop(self) -> None:
        while True:
            item = await self._queue.get()
            self._pending.discard(item.schedule_id)
            try:
                await self._run_saved(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A failed run has logged its traceback already; this says
                # which schedule it belonged to.
                logger.error(
                    "%s schedule %s failed: %s",
                    self.kind.capitalize(),
                    item.schedule_id,
                    exc,
                )
            finally:
                self._queue.task_done()

    async def _run_saved(self, item: _QueuedRun) -> None:
        async with self._database.read_session() as session:
            record = await SavedScheduleRepository(session).get(item.schedule_id)
            schedule = (
                self._detach(record)
                if record is not None
                and record.kind == self.kind
                and (item.force or record.enabled)
                else None
            )
        if schedule is None:
            self._announce()
            return

        self._active = _ActiveRun(schedule.id, schedule.name)
        self._announce()
        try:
            state = await self._run(schedule, self._report)
            async with self._database.write_session() as session:
                record = await SavedScheduleRepository(session).get(item.schedule_id)
                if record is not None and record.kind == self.kind:
                    record.last_run_at = utc_now()
                    if state is not None:
                        record.state = state
                    session.add(record)
        finally:
            self._active = None
            self._announce()

    def _detach(self, record: SavedSchedule) -> NamedSchedule[ConfigT]:
        schedule_id = record.id
        if schedule_id is None:
            raise ValueError("Schedule has not been saved")
        run_status, waiting_for = self._run_view(schedule_id)
        return NamedSchedule(
            id=schedule_id,
            kind=self.kind,
            name=record.name,
            enabled=bool(record.enabled),
            cron_expression=record.cron_expression,
            timezone=self._app_config.TZ,
            next_run=self.scheduler.job_info(_job_id(schedule_id)).next_run,
            config=self._config_model.model_validate(record.payload),
            state=dict(record.state),
            created_at=record.created_at,
            updated_at=record.updated_at,
            last_run_at=record.last_run_at,
            run_status=run_status,
            waiting_for=waiting_for,
        )

    def _run_view(self, schedule_id: int) -> tuple[ScheduleRunStatus, str | None]:
        """Return what the queue is doing with *schedule_id*, and why it waits."""
        active = self._active
        if active is not None and active.schedule_id == schedule_id:
            if active.waiting_for:
                return "waiting", active.waiting_for
            return "running", None
        if schedule_id in self._pending:
            return "queued", active.name if active is not None else None
        return "idle", None

    def _response(self, record: SavedSchedule) -> ResponseT:
        return self._response_model.model_validate(
            self._detach(record), from_attributes=True
        )


def _job_id(schedule_id: int) -> str:
    return f"saved_schedule:{schedule_id}"
