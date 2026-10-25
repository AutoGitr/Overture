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
lazy from ...jobs.runner import JobContext
lazy from ...jobs.slot import ManagedBackgroundJob
lazy from ...jobs.tally import SyncTally
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...schemas.common import StatusResponse
lazy from ...schemas.sync import (
    IncrementalSyncState,
    SyncRunRequest,
    SyncScheduleConfig,
    SyncScheduleResponse,
)
lazy from ...utils.time import format_duration, utc_now
lazy from ..downloads.service import DownloadService
lazy from ..local_assets.service import LocalAssets
lazy from ..named_schedules import NamedSchedule, NamedSchedules
lazy from ..public_dataset.downloads import (
    QueuedDownloads,
    queue_overturedb_downloads_for_items,
)
lazy from ..schedule_store import SYNC_SERVER_SCHEDULE, load_schedule, patch_payload
lazy from ..scheduler import SchedulerService
lazy from .collection_sync import CollectionSync
lazy from .reconciler import LibraryReconciler
lazy from .runner import run_sync as _run_sync
lazy from .tmdb_collections import TmdbCollectionEnrichment
lazy from .tmdb_seasons import TmdbSeasonSync

logger = logging.getLogger(__name__)


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
    ) -> None:
        """Initialize instance state."""
        self._app_config = app_config
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
        self._collections = CollectionSync(
            provider_registry=provider_registry,
            enrichment=TmdbCollectionEnrichment(
                app_config=app_config, database=database, tmdb_client=tmdb_client
            ),
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
            self._app_config.MEDIA_SERVER, self._app_config.MEDIA_SERVER_URL
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
    ) -> dict[str, Any] | None:
        """Run one saved schedule in the sync slot once the slot is free.

        A full sync also waits for Assets, Renamer and Audit to finish; polling
        only adds items, so it shares the library with them.
        """
        config = schedule.config
        library_ids = config.library_ids or None
        if config.mode == "full":
            await self._library_gate.run(
                "sync",
                self.job,
                self._full_sync(
                    library_ids, include_collections=config.include_collections
                ),
                report=report,
            )
            return None

        state = IncrementalSyncState.model_validate(schedule.state)
        polled: list[IncrementalSyncState] = []

        async def poll(context: JobContext) -> None:
            await context.publish_lifecycle("started", quiet=True)
            if (result := await self._poll_new_media(config, state)) is not None:
                polled.append(result)
            await context.publish_lifecycle(
                "completed",
                snapshot=True,
                quiet=True,
                finished_at=utc_now().isoformat(),
            )

        if self.job.running:
            report(self.job.name)
        await self.job.run_when_idle(poll, on_start=lambda _task: report(None))
        return polled[0].model_dump(mode="json") if polled else None

    async def _poll_new_media(
        self, config: SyncScheduleConfig, state: IncrementalSyncState
    ) -> IncrementalSyncState | None:
        """Poll for newly added media without running a full reconciliation.

        Returns the advanced state, or ``None`` when the checkpoint must stay
        where it is so the next poll covers this window again.
        """
        now = utc_now()
        since = state.checkpoint
        if since is None:
            logger.info(
                "Incremental sync will look for media added from %s",
                now.isoformat(timespec="seconds"),
            )
            return IncrementalSyncState(checkpoint=now)

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
        items_added = len(created)
        if errors:
            return None
        return IncrementalSyncState(
            checkpoint=now,
            last_duration_seconds=round(duration, 2),
            last_items_added=items_added,
            last_downloads=downloads_count,
        )

    def start_background_sync(
        self,
        *,
        library_ids: list[str] | None = None,
        include_collections: bool = True,
    ) -> bool:
        """Start a full sync now, returning False if the slot is busy.

        Raises:
            PublicServiceError: While Assets, Renamer or Audit is running.
        """
        return self._library_gate.start(
            "sync",
            self.job,
            self._full_sync(library_ids, include_collections=include_collections),
        )

    def _full_sync(
        self, library_ids: list[str] | None, *, include_collections: bool = True
    ) -> Callable[[JobContext], Coroutine[Any, Any, None]]:
        """Return the job body for one full sync of *library_ids*."""
        return lambda context: _run_sync(
            context,
            library_ids=library_ids,
            include_collections=include_collections,
            provider_registry=self.provider_registry,
            reconciler=self.reconciler,
            config_dir=self._config_dir,
            tmdb_seasons=self._tmdb_seasons,
            collections=self._collections,
        )

    def run_sync(self, body: SyncRunRequest) -> StatusResponse:
        """Trigger a sync run."""
        return StatusResponse.start(
            self.start_background_sync(
                library_ids=body.library_ids or None,
                include_collections=body.include_collections,
            )
        )
