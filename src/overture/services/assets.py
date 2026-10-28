"""Assets runs - bulk art and theme jobs started together - and their schedules."""

lazy import asyncio
lazy from collections.abc import Callable, Coroutine
lazy from dataclasses import dataclass
lazy from typing import Any

lazy from .. import protocols
lazy from ..config import Settings
lazy from ..db.session import Database
lazy from ..domain import ScheduleKind
lazy from ..jobs.gate import WaitReporter
lazy from ..jobs.runner import JobContext, scheduled
lazy from ..jobs.slot import ManagedBackgroundJob
lazy from ..schemas.bulk import (
    BulkAssetsRequest,
    BulkAssetsRunResponse,
    BulkAssetsScheduleResponse,
    BulkAssetsStopRequest,
    BulkMatchArtRequest,
    BulkThemeRequest,
)
lazy from ..schemas.common import Status, StatusResponse
lazy from ..ws.state import BackgroundJobRegistry
lazy from .art.bulk import run_bulk_art_match
lazy from .art.matcher import ArtMatcher
lazy from .art.service import ArtService
lazy from .downloads.service import DownloadService
lazy from .local_assets.service import LocalAssets
lazy from .named_schedules import (
    NamedSchedule,
    NamedSchedules,
    ScheduleRunResult,
    job_run_summary,
)
lazy from .scheduler import SchedulerService
lazy from .themes.bulk import run_bulk_themes
lazy from .themes.youtube_resolver import YouTubeResolver

#: The counters of an Assets run's jobs, as its schedule shows them.
_ASSETS_COUNTERS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "queued": "queued",
        "adopted": "adopted",
        "skipped": "skipped",
        "no_match": "unmatched",
        "errors": "failed",
    }
)


@dataclass(slots=True, frozen=True)
class _AssetsJobRun:
    """One selected internal job for a unified assets run."""

    job: ManagedBackgroundJob
    factory: Callable[[JobContext], Coroutine[Any, Any, None]]


class AssetsService:
    """Owns unified assets runs and the saved assets schedules."""

    def __init__(
        self,
        *,
        background_jobs: BackgroundJobRegistry,
        downloads: DownloadService,
        art_matcher: ArtMatcher,
        art: ArtService,
        youtube_resolver: YouTubeResolver,
        scheduler: SchedulerService,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        local_assets: LocalAssets,
        database: Database,
    ) -> None:
        self._app_config = app_config
        self._database = database
        self.background_jobs = background_jobs
        self.downloads = downloads
        self.art_matcher = art_matcher
        self._art = art
        self.local_assets = local_assets
        self.youtube_resolver = youtube_resolver
        self.schedules = NamedSchedules(
            ScheduleKind.ASSETS,
            config_model=BulkAssetsRequest,
            response_model=BulkAssetsScheduleResponse,
            run=self._run_schedule,
            scheduler=scheduler,
            publisher=publisher,
            app_config=app_config,
            database=database,
        )

    @property
    def healthy(self) -> bool:
        """Return whether saved schedules are still being processed."""
        return self.schedules.healthy

    async def start(self) -> None:
        """Register saved schedules and start running them."""
        await self.schedules.start()

    async def stop(self) -> None:
        """Stop running saved schedules."""
        await self.schedules.stop()

    def start_run(self, params: BulkAssetsRequest) -> BulkAssetsRunResponse:
        """Start the selected jobs now, each unless its slot is busy."""
        response = BulkAssetsRunResponse()
        for run in self._selected_runs(params):
            status = (
                "started"
                if self.background_jobs.library_gate.start(
                    "assets", run.job, run.factory
                )
                else "already_running"
            )
            if run.job is self.background_jobs.art_match:
                response.art = status
            else:
                response.themes = status
        return response

    def stop_run(self, params: BulkAssetsStopRequest) -> StatusResponse:
        """Stop selected bulk runs; each run cancels only its own downloads."""
        jobs = [
            job
            for job, selected in (
                (self.background_jobs.art_match, params.art),
                (self.background_jobs.theme_match, params.themes),
            )
            if selected
        ]
        if not jobs:
            return StatusResponse(status=Status.NO_JOBS_SELECTED)

        stopping = [job.request_stop() for job in jobs]
        return StatusResponse(status=Status.STOPPING if any(stopping) else Status.IDLE)

    async def _run_schedule(
        self, schedule: NamedSchedule[BulkAssetsRequest], report: WaitReporter
    ) -> ScheduleRunResult:
        """Start the selected jobs once their slots are free, then await them.

        A scheduled run waits for a running full sync and for whatever is
        already in each slot, rather than polling either on a timer.
        """
        runs = self._selected_runs(schedule.config)
        waits: dict[str, str] = {}

        def reporter(job_name: str) -> WaitReporter:
            def note(waiting_for: str | None) -> None:
                if waiting_for is None:
                    waits.pop(job_name, None)
                else:
                    waits[job_name] = waiting_for
                report(", ".join(dict.fromkeys(waits.values())) or None)

            return note

        await asyncio.gather(
            *(
                self.background_jobs.library_gate.run(
                    "assets",
                    run.job,
                    scheduled(run.factory, schedule.name),
                    report=reporter(run.job.name),
                )
                for run in runs
            )
        )
        return ScheduleRunResult(
            job_run_summary(
                (run.job.last_payload for run in runs),
                _ASSETS_COUNTERS,
                failed=any(
                    (run.job.last_event or "").endswith(".failed") for run in runs
                ),
            )
        )

    def _selected_runs(self, config: BulkAssetsRequest) -> list[_AssetsJobRun]:
        runs: list[_AssetsJobRun] = []
        art_params = config.art_request()
        theme_params = config.theme_request()
        if art_params is not None:
            runs.append(
                _AssetsJobRun(
                    job=self.background_jobs.art_match,
                    factory=lambda context, params=art_params: self._run_art_worker(
                        context, params
                    ),
                )
            )
        if theme_params is not None:
            runs.append(
                _AssetsJobRun(
                    job=self.background_jobs.theme_match,
                    factory=lambda context, params=theme_params: self._run_theme_worker(
                        context, params
                    ),
                )
            )
        return runs

    async def _run_art_worker(
        self,
        context: JobContext,
        params: BulkMatchArtRequest,
    ) -> None:
        await run_bulk_art_match(
            context,
            params,
            self.downloads,
            self.art_matcher,
            art=self._art,
            local_assets=self.local_assets,
            app_config=self._app_config,
            database=self._database,
        )

    async def _run_theme_worker(
        self,
        context: JobContext,
        params: BulkThemeRequest,
    ) -> None:
        await run_bulk_themes(
            context,
            params,
            self.downloads,
            self.youtube_resolver,
            app_config=self._app_config,
            local_assets=self.local_assets,
            database=self._database,
        )
