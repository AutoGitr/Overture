"""SyncEngine - synchronises media library with the configured Media Server."""

lazy import logging
lazy import time
lazy from collections.abc import Callable, Coroutine
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ... import protocols
lazy from ...config import Settings, media_server_identity
lazy from ...db.session import Database
lazy from ...domain import ScheduleKind
lazy from ...integrations.tmdb import TMDBClient
lazy from ...jobs.gate import LibraryGate, WaitReporter
lazy from ...jobs.kinds import JobKind
lazy from ...jobs.lifecycle import ManagedJobLifecycle
lazy from ...jobs.runner import JobContext, scheduled
lazy from ...jobs.slot import ManagedBackgroundJob
lazy from ...jobs.tally import SyncTally
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...schemas.common import StatusResponse
lazy from ...schemas.schedules import ScheduleRunSummary
lazy from ...schemas.sync import (
    IncrementalSyncState,
    SyncRunRequest,
    SyncScheduleConfig,
    SyncScheduleResponse,
)
lazy from ...utils.time import format_duration, utc_now
lazy from ..downloads.service import DownloadService
lazy from ..local_assets.service import LocalAssets
lazy from ..named_schedules import (
    NamedSchedule,
    NamedSchedules,
    ScheduleRunResult,
    job_run_summary,
)
lazy from ..public_dataset.downloads import (
    QueuedDownloads,
    queue_overturedb_downloads_for_items,
)
lazy from ..schedule_store import SYNC_SERVER_SCHEDULE, load_schedule, patch_payload
lazy from ..scheduler import SchedulerService
lazy from .collection_sync import CollectionSync
lazy from .reconciler import LibraryReconciler
lazy from .runner import run_sync as _run_sync
lazy from .tmdb_enrichment import TmdbEnrichment
lazy from .tmdb_seasons import TmdbSeasonSync

logger = logging.getLogger(__name__)

#: The counters of a full sync, as its schedule shows them.
_FULL_SYNC_COUNTERS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "added": "added",
        "updated": "updated",
        "removed": "removed",
        "errors": "failed",
    }
)


class SyncEngine:
    """Owns the sync slot, its saved schedules, and full and incremental runs."""

    def __init__(
        self,
        *,
        downloads: DownloadService,
        provider_registry: ProviderRegistry,
        scheduler: SchedulerService,
        publisher: protocols.EventPublisher,
        library_gate: LibraryGate,
        local_assets: LocalAssets,
        app_config: Settings,
        database: Database,
        config_dir: Path,
        tmdb_client: TMDBClient,
        groups: protocols.CollectionGroups,
    ) -> None:
        """Initialize instance state."""
        self._app_config = app_config
        self._groups = groups
        self._database = database
        self._config_dir = config_dir
        self._publisher = publisher
        self._library_gate = library_gate
        self.downloads = downloads
        self.provider_registry = provider_registry
        self._tmdb_seasons = TmdbSeasonSync(
            app_config=app_config,
            database=database,
            tmdb_client=tmdb_client,
            publisher=publisher,
        )
        self._enrichment = TmdbEnrichment(
            app_config=app_config, database=database, tmdb_client=tmdb_client
        )
        self._collections = CollectionSync(
            provider_registry=provider_registry,
            publisher=publisher,
            app_config=app_config,
            database=database,
            downloads=downloads,
        )
        self.reconciler = LibraryReconciler(
            publisher=publisher,
            local_assets=local_assets,
            downloads=downloads,
            app_config=app_config,
            database=database,
        )
        self.job = ManagedBackgroundJob(
            ManagedJobLifecycle(JobKind.SYNC), publisher, database=database
        )
        self.schedules = NamedSchedules(
            ScheduleKind.SYNC,
            config_model=SyncScheduleConfig,
            response_model=SyncScheduleResponse,
            run=self._run_schedule,
            scheduler=scheduler,
            publisher=publisher,
            app_config=app_config,
            database=database,
        )

    async def _reconcile_server_transition(self) -> None:
        """Reset saved sync schedules when the media server has changed.

        Library IDs and incremental checkpoints belong to the server that
        issued them; on another server they would select nothing useful.
        """
        current_server = media_server_identity(
            self._app_config.MEDIA_SERVER or "", self._app_config.MEDIA_SERVER_URL
        )
        async with self._database.read_session() as session:
            saved = await load_schedule(session, SYNC_SERVER_SCHEDULE)
        last_server = saved.payload.last_media_server
        if last_server == current_server:
            return
        if last_server is not None:
            logger.info(
                "Media server changed; resetting sync schedule "
                "libraries and incremental checkpoints",
            )
            await self.schedules.reset(
                lambda config: config.model_copy(update={"library_ids": []})
            )
        async with self._database.write_session() as session:
            await patch_payload(
                session, SYNC_SERVER_SCHEDULE, last_media_server=current_server
            )

    async def start(self) -> None:
        """Reconcile saved schedules with the active server, then register them."""
        await self._reconcile_server_transition()
        await self.schedules.start()

    async def stop(self) -> None:
        """Stop scheduled runs and the running sync."""
        await self.schedules.stop()
        await self.job.shutdown()
        logger.debug("Sync stopped")

    async def _run_schedule(
        self, schedule: NamedSchedule[SyncScheduleConfig], report: WaitReporter
    ) -> ScheduleRunResult:
        """Run one saved schedule in the sync slot once the slot is free.

        A full sync also waits for Assets, Renamer and Audit to finish; polling
        only adds items, so it shares the library with them.
        """
        config = schedule.config
        if config.mode == "full":
            await self._library_gate.run(
                "sync",
                self.job,
                scheduled(self._full_sync(config), schedule.name),
                report=report,
            )
            event, payload = self.job.final_snapshot()
            summary = job_run_summary(
                [payload],
                _FULL_SYNC_COUNTERS,
                failed=(event or "").endswith(".failed"),
            )
            await self.job.retire_result(payload)
            return ScheduleRunResult(summary)

        state = IncrementalSyncState.model_validate(schedule.state)
        polled: list[tuple[IncrementalSyncState | None, ScheduleRunSummary]] = []

        async def poll(context: JobContext) -> None:
            await context.publish_lifecycle("started", quiet=True)
            polled.append(await self._poll_new_media(config, state))
            await context.publish_lifecycle(
                "completed",
                snapshot=True,
                quiet=True,
                finished_at=utc_now().isoformat(),
            )

        if self.job.running:
            report(self.job.name)
        await self.job.run_when_idle(poll, on_start=lambda _task: report(None))
        # Like any run it replaces the previous result, and as a scheduled one
        # it leaves none: its schedule reports what it did.
        await self.job.retire_result(self.job.final_snapshot()[1])
        [(advanced, summary)] = polled
        return ScheduleRunResult(
            summary, None if advanced is None else advanced.model_dump(mode="json")
        )

    async def _poll_new_media(
        self, config: SyncScheduleConfig, state: IncrementalSyncState
    ) -> tuple[IncrementalSyncState | None, ScheduleRunSummary]:
        """Poll for newly added media without running a full reconciliation.

        Returns the advanced state, or ``None`` when the checkpoint must stay
        where it is so the next poll covers this window again, and what the
        poll did.
        """
        now = utc_now()
        since = state.checkpoint
        if since is None:
            logger.info(
                "Incremental sync will look for media added from %s",
                now.isoformat(timespec="seconds"),
            )
            return IncrementalSyncState(checkpoint=now), ScheduleRunSummary()

        provider = self.provider_registry.provider
        library_ids = config.library_ids or None
        logger.debug(
            "Incremental sync: checking for media added since %s",
            since.isoformat(timespec="seconds"),
        )
        start_time = time.monotonic()
        tally = SyncTally()
        created: list[int] = []
        queued = QueuedDownloads()
        try:
            await self.reconciler.record_libraries(await provider.get_sections())
            async for recent_items in provider.iter_items_since(
                since=since, library_ids=library_ids
            ):
                await self.reconciler.fill_deferred_directors(provider, recent_items)
                stats = await self.reconciler.sync_recent(recent_items, tally=tally)
                created.extend(stats.created_item_ids)
                queued += await queue_overturedb_downloads_for_items(
                    stats.created_item_ids,
                    include_art=config.download_overturedb_art,
                    theme_order=config.download_themes,
                    downloads=self.downloads,
                    app_config=self._app_config,
                    database=self._database,
                )
        except (httpx2.HTTPError, SQLAlchemyError, OSError, ValueError) as exc:
            raise RuntimeError("Incremental sync failed") from exc
        # New titles get their TMDB facts now, so criteria match them before
        # the next full sync.
        await self._enrichment.read_new(created)
        duration = max(0.0, time.monotonic() - start_time)
        errors = tally.errors + queued.errors
        downloads_count = queued.total
        # A poll that found nothing new is routine; one that changed the
        # library, queued downloads or hit errors is worth reading.
        logger.log(
            logging.INFO
            if tally.added or tally.updated or downloads_count or errors
            else logging.DEBUG,
            "Incremental sync finished in %s - added %d, updated %d, unchanged %d, "
            "errors %d; queued %d artwork and %d theme downloads (%d failed to queue)",
            format_duration(duration),
            tally.added,
            tally.updated,
            tally.unchanged,
            tally.errors,
            queued.art,
            queued.themes,
            queued.errors,
        )
        counts = {"added": len(created), "queued": downloads_count, "failed": errors}
        summary = ScheduleRunSummary(
            duration_seconds=round(duration, 2),
            counts={name: count for name, count in counts.items() if count},
            failed=bool(errors),
        )
        return (None if errors else IncrementalSyncState(checkpoint=now)), summary

    def start_background_sync(self, body: SyncRunRequest | None = None) -> bool:
        """Start a full sync now, of every library unless *body* says otherwise.

        Returns False if the slot is busy.

        Raises:
            PublicServiceError: While Assets, Renamer or Audit is running.
        """
        return self._library_gate.start(
            "sync", self.job, self._full_sync(body or SyncRunRequest())
        )

    def _full_sync(
        self, body: SyncRunRequest | SyncScheduleConfig
    ) -> Callable[[JobContext], Coroutine[Any, Any, None]]:
        """Return the job body for one full sync; no libraries means every one."""
        return lambda context: _run_sync(
            context,
            library_ids=body.library_ids or None,
            items=body.items,
            include_collections=body.include_collections,
            collection_groups=body.collection_groups,
            provider_registry=self.provider_registry,
            reconciler=self.reconciler,
            config_dir=self._config_dir,
            tmdb_seasons=self._tmdb_seasons,
            enrichment=self._enrichment,
            collections=self._collections,
            groups=self._groups,
        )

    def run_sync(self, body: SyncRunRequest) -> StatusResponse:
        """Trigger a sync run."""
        return StatusResponse.start(self.start_background_sync(body))
