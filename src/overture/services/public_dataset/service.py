"""Public dataset service: scheduling, sync lifecycle, and status.

Catalog I/O lives in ``catalog``. Candidate and record lookup lives in ``lookup``.
"""

lazy import logging
lazy from pathlib import Path

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.session import Database
lazy from ...jobs.kinds import JobKind
lazy from ...jobs.lifecycle import ManagedJobLifecycle
lazy from ...jobs.progress_log import JobLogEntry, JobOutcome, log_entry
lazy from ...jobs.runner import JobContext
lazy from ...jobs.slot import ManagedBackgroundJob
lazy from ...schemas.common import Status, StatusResponse
lazy from ...schemas.public_dataset import (
    PublicDatasetRecord,
    PublicDatasetSources,
    PublicDatasetStatus,
    PublicDatasetSyncStats,
)
lazy from ...utils.errors import public_error_message
lazy from ...utils.temporary import operation_directory
lazy from ...utils.time import utc_now, utc_now_iso
lazy from ..schedule_store import (
    PUBLIC_DATASET_SCHEDULE,
    PublicDatasetPayload,
    Schedule,
    load_schedule,
    patch_payload,
    save_schedule,
)
lazy from ..scheduler import SchedulerService
lazy from . import catalog, staging
lazy from .browse import CatalogBrowser
lazy from .lookup import get_record_for_item, get_sources_for_item

logger = logging.getLogger(__name__)

#: The scheduler job that syncs the catalog.
_SCHEDULED_SYNC_JOB = "public_dataset_sync"


class PublicDatasetService:
    """Scheduling, sync lifecycle, and status for the public dataset.

    Heavy lifting is split across ``catalog``, ``lookup`` and ``browse``.
    """

    def __init__(
        self,
        *,
        scheduler: SchedulerService,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        database: Database,
        config_dir: Path,
    ) -> None:
        self._app_config = app_config
        self._database = database
        self._config_dir = config_dir
        self._publisher = publisher
        self.scheduler = scheduler
        self.catalog = CatalogBrowser(database=database, app_config=app_config)
        self.job = ManagedBackgroundJob(
            ManagedJobLifecycle(
                JobKind.PUBLIC_DATASET_SYNC,
                event_job_id="public-dataset:sync",
                target={"catalog_url": catalog.get_public_dataset_catalog_url()},
            ),
            publisher,
            database=database,
        )

    async def start(self) -> None:
        """Start the public dataset scheduler."""
        async with self._database.read_session() as session:
            schedule = await load_schedule(
                session, PUBLIC_DATASET_SCHEDULE, timezone=self._app_config.TZ
            )
        self._schedule_job(schedule)
        logger.debug("OvertureDB scheduler started")

    async def stop(self) -> None:
        """Stop the public dataset scheduler."""
        await self.job.shutdown()
        logger.debug("OvertureDB scheduler stopped")

    async def set_enabled(self, enabled: bool) -> PublicDatasetStatus:
        """Persist enabled state and reschedule accordingly."""
        async with self._database.write_session() as session:
            schedule = await save_schedule(
                session,
                PUBLIC_DATASET_SCHEDULE,
                enabled=enabled,
                timezone=self._app_config.TZ,
            )
        self._schedule_job(schedule)
        return self.status_from_schedule(schedule)

    async def get_status(self) -> PublicDatasetStatus:
        """Return the public dataset's state and its last sync."""
        async with self._database.read_session() as session:
            schedule = await load_schedule(
                session, PUBLIC_DATASET_SCHEDULE, timezone=self._app_config.TZ
            )
        return self.status_from_schedule(schedule)

    def status_from_schedule(
        self, schedule: Schedule[PublicDatasetPayload]
    ) -> PublicDatasetStatus:
        """Return the public status a saved schedule describes."""
        return PublicDatasetStatus(
            enabled=schedule.enabled,
            repo_url=catalog.PUBLIC_DATASET_REPO_URL,
            catalog_url=catalog.get_public_dataset_catalog_url(),
            last_synced_at=schedule.payload.last_synced_at,
            last_status=schedule.payload.last_status,
            last_stats=schedule.payload.last_stats,
            timezone=schedule.timezone,
            next_run=self.scheduler.job_info(_SCHEDULED_SYNC_JOB).next_run,
        )

    def _schedule_job(self, schedule: Schedule[PublicDatasetPayload]) -> None:
        if self.scheduler.set_cron_job(
            _SCHEDULED_SYNC_JOB,
            enabled=schedule.enabled,
            func=self._run_scheduled_sync,
            cron_expression=schedule.cron_expression,
        ):
            logger.info("OvertureDB sync scheduled (%s)", schedule.cron_expression)
        else:
            logger.info("Scheduled OvertureDB sync disabled")

    async def _run_scheduled_sync(self) -> None:
        if not self.start_background_sync():
            logger.info("Skipped a scheduled OvertureDB sync: one is already running")

    async def sync_now(self) -> StatusResponse:
        """Start a catalog sync, unless the dataset is off or one is running."""
        if not (await self.get_status()).enabled:
            return StatusResponse(status=Status.DISABLED)
        return StatusResponse.start(self.start_background_sync())

    @staticmethod
    async def _publish_sync_event(
        status: str,
        *,
        context: JobContext,
        stats: PublicDatasetSyncStats,
        log: JobLogEntry | None = None,
        error: str | None = None,
        snapshot: bool = False,
    ) -> None:
        await context.publish_lifecycle(
            status,
            finished_at=utc_now_iso() if status in {"completed", "failed"} else None,
            stats=stats.model_dump(),
            log=log,
            error=error,
            snapshot=snapshot,
        )

    async def run_sync(self, context: JobContext) -> None:
        """Download, validate, and persist the public-dataset catalog."""
        synced_at = utc_now()
        stats = PublicDatasetSyncStats()

        try:
            await self._publish_sync_event(
                "started",
                context=context,
                stats=stats,
                log=log_entry(
                    JobOutcome.STARTED, "OvertureDB sync", "downloading the catalog"
                ),
            )
            with operation_directory(self._config_dir) as directory:
                source = directory / "catalog.jsonl"
                snapshot = directory / "catalog.sqlite"
                await staging.download(source, stats)
                stats.entries = await staging.prepare(
                    source, snapshot, app_config=self._app_config
                )
                await self._publish_sync_event(
                    "progress",
                    context=context,
                    stats=stats,
                    log=log_entry(
                        JobOutcome.CHECKED,
                        "OvertureDB catalog",
                        f"validated {stats.entries} entries; importing",
                    ),
                )
                async with self._database.write_session() as session:
                    await staging.replace(session, snapshot, synced_at, stats)
                    await patch_payload(
                        session,
                        PUBLIC_DATASET_SCHEDULE,
                        last_status="success",
                        last_synced_at=synced_at,
                        last_stats=stats,
                    )
        except (
            httpx2.HTTPError,
            ValueError,
            TypeError,
            OSError,
            SQLAlchemyError,
        ) as exc:
            # The replacement transaction rolled back; no imported rows survived.
            stats = stats.model_copy(
                update={
                    "errors": stats.errors + 1,
                    "items": 0,
                    "movies": 0,
                    "shows": 0,
                    "seasons": 0,
                }
            )
            async with self._database.write_session() as session:
                await patch_payload(
                    session,
                    PUBLIC_DATASET_SCHEDULE,
                    last_status="failed",
                    last_stats=stats,
                )
            await self._publish_sync_event(
                "failed",
                context=context,
                stats=stats,
                error=public_error_message(exc),
                snapshot=True,
            )
        else:
            await self._publish_sync_event(
                "completed",
                context=context,
                stats=stats,
                log=log_entry(
                    JobOutcome.UPDATED,
                    "OvertureDB catalog",
                    f"imported {stats.items} items "
                    f"({stats.movies} movies, {stats.shows} shows, "
                    f"{stats.seasons} seasons) and {stats.collections} collections",
                ),
                snapshot=True,
            )
        await self._publisher.broadcast(
            "public-dataset.updated", await self.get_status()
        )

    def start_background_sync(self) -> bool:
        """Kick off a background sync task; returns False if already running."""
        return self.job.start_with_context(self.run_sync)

    async def get_sources_for_item(self, item_id: int) -> PublicDatasetSources:
        """Look up public dataset candidates for an item."""
        return await get_sources_for_item(
            item_id, app_config=self._app_config, database=self._database
        )

    async def get_record_for_item(self, item_id: int) -> PublicDatasetRecord:
        """Look up public dataset record for an item."""
        return await get_record_for_item(item_id, database=self._database)
