"""Persistent download queue and worker manager."""

lazy import asyncio
lazy import logging
lazy from collections.abc import Awaitable, Callable, Generator, Iterable
lazy from contextlib import contextmanager
lazy from itertools import batched

lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import CHUNK_SIZE, PAGE_SIZE, Database
lazy from ...domain import ACTIVE_JOB_STATUSES, JobStatus, JobType, ServerAsset
lazy from ...jobs.kinds import DownloadStatus
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...schemas.downloads import DownloadJobEvent, DownloadJobsPage
lazy from ...utils.errors import public_error_message
lazy from ...utils.file import compute_bytes_hash
lazy from ...utils.image import RemoteImageError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..library.items import emit_library_item_upserted
lazy from ..storage.assets import (
    AssetStorage,
    MissingLocalPathError,
    PathTraversalError,
    StoredFile,
    TargetDirectoryMissingError,
)
lazy from ..themes.youtube_resolver import (
    DownloadError,
    DurationError,
    TranscodeError,
)
lazy from .art import DownloadArtHandler, DownloadedArt
lazy from .collection_theme import upload_collection_theme, verify_collection_upload
lazy from .events import DownloadEventPublisher
lazy from .protocols import DownloadResult, PreparedDownload
lazy from .queue import JobTarget, add_job, after_commit
lazy from .recovery import WriteIntent, selection_state, verified_write
lazy from .theme import DownloadedTheme, DownloadThemeHandler
lazy from .watch import DownloadWatch

logger = logging.getLogger(__name__)

#: The job types each worker lane drains. Artwork is a short fetch and a file
#: write; a theme is a YouTube download and a transcode that can run for a
#: minute. They are queued apart, and sized apart, so a library's worth of
#: posters cannot end up stuck behind one theme in a single line.
_LANES: frozendict[JobType, tuple[JobType, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        JobType.ART: (JobType.ART,),
        JobType.THEME: (JobType.THEME, JobType.COLLECTION_THEME),
    }
)
#: The lane each job type is drained by.
_LANE_OF = frozendict(
    {job_type: lane for lane, types in _LANES.items() for job_type in types}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
#: Errors that fail one job and leave its lane running.
_JOB_ERRORS = (
    MissingLocalPathError,
    PathTraversalError,
    TargetDirectoryMissingError,
    RemoteImageError,
    DurationError,
    DownloadError,
    TranscodeError,
    MediaServerError,
)


def _replaced_assets(job: DownloadJob) -> tuple[ServerAsset, ...]:
    """Return the assets of the refreshed item that a finished download replaces.

    A season poster belongs to the season rather than the refreshed item, so
    it unlocks nothing there.
    """
    if job.job_type is JobType.THEME:
        return (ServerAsset.THEME,)
    if job.art_type is None or job.art_type.owned_by_season:
        return ()
    return (job.art_type.server_asset,)


def _job_title(job: DownloadJob, item: MediaItem | None) -> str | None:
    """Return the name a job's events use for what it writes."""
    if job.job_type is JobType.COLLECTION_THEME:
        return job.collection_title
    return item.title if item else None


class DownloadService:
    """Manage queue lifecycle, crash recovery, and worker dispatch."""

    def __init__(
        self,
        *,
        art_handler: DownloadArtHandler,
        theme_handler: DownloadThemeHandler,
        provider_registry: ProviderRegistry,
        events: DownloadEventPublisher,
        publisher: protocols.EventPublisher,
        asset_storage: AssetStorage,
        app_config: Settings,
        database: Database,
    ) -> None:
        self._database = database
        self.art_handler = art_handler
        self.theme_handler = theme_handler
        self.provider_registry = provider_registry
        self._events = events
        self._publisher = publisher
        self._asset_storage = asset_storage
        self._lane_sizes = {
            JobType.ART: app_config.ART_DOWNLOAD_WORKERS,
            JobType.THEME: app_config.THEME_DOWNLOAD_WORKERS,
        }
        self._wake = {lane: asyncio.Event() for lane in _LANES}
        self._stopping = False
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._watches: set[DownloadWatch] = set()
        self._running_jobs: dict[str, asyncio.Task[None]] = {}
        self._committing_jobs: dict[str, asyncio.Task[bool]] = {}

    async def queue_job(
        self,
        session: AsyncSession,
        target: JobTarget,
        *,
        on_queued: Callable[[str], None] | None = None,
    ) -> tuple[str, bool]:
        """Add a job for *target* to the caller's transaction, unless one is active.

        The job's lane wakes, and *on_queued* is called with the new job's ID,
        once the caller's transaction commits: a caller following its own
        downloads is told before the job can start.

        Returns:
            The job's ID, and whether it is new.
        """
        if self._stopping:
            raise RuntimeError("Downloads are stopping")
        job_id, created = await add_job(session, target)
        if created:

            def queued() -> None:
                if on_queued is not None:
                    on_queued(job_id)
                self._wake[_LANE_OF[target.job_type]].set()

            after_commit(session, queued)
        return job_id, created

    async def start(self) -> None:
        """Start each lane's workers and requeue pending/running rows."""
        if self._worker_tasks:
            return
        self._stopping = False
        await self._recover_jobs()
        if self._stopping:
            return
        for lane, size in self._lane_sizes.items():
            for _ in range(size):
                task = asyncio.create_task(self._worker_loop(lane))
                task.add_done_callback(self._worker_done)
                self._worker_tasks.append(task)
        logger.debug(
            "Download workers started: %s",
            ", ".join(
                f"{size} {lane} workers" for lane, size in self._lane_sizes.items()
            ),
        )

    async def stop(self) -> None:
        """Stop claims cooperatively and cancel active downloads."""
        self._stopping = True
        for wake in self._wake.values():
            wake.set()
        for task in tuple(self._running_jobs.values()):
            task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks.clear()
        logger.debug("Download workers stopped")

    @property
    def healthy(self) -> bool:
        """Every configured worker must be alive."""
        alive = sum(not task.done() for task in self._worker_tasks)
        return not self._stopping and alive == sum(self._lane_sizes.values())

    @contextmanager
    def watch(self) -> Generator[DownloadWatch]:
        """Follow the jobs queued through the watch, for as long as it is held."""
        watch = DownloadWatch()
        self._watches.add(watch)
        try:
            yield watch
        finally:
            self._watches.discard(watch)

    async def cancel_jobs(self, job_ids: Iterable[str]) -> None:
        """Cancel pending or running download jobs by ID."""
        ids = set(job_ids)
        if not ids:
            return

        now = utc_now()
        cancelled_jobs: list[tuple[DownloadJob, str]] = []
        tasks: list[Awaitable[object]] = []
        async with self._database.write_session() as session:
            repo = DownloadJobRepository(session)
            active_jobs: list[tuple[DownloadJob, str]] = []
            for batch in batched(ids, CHUNK_SIZE, strict=False):
                active_jobs.extend(await repo.list_active_with_titles(job_ids=batch))
            # Classify without yielding: a prepared download can start saving
            # while the queries above are awaiting the database.
            for job, title in active_jobs:
                if commit := self._committing_jobs.get(job.id):
                    tasks.append(commit)
                    continue
                cancelled_jobs.append((job, title))
                job.status = JobStatus.CANCELLED
                job.completed_at = now
                job.write_intent = None
                session.add(job)

            # Cancel while holding the write lock so queued jobs cannot start
            # between being marked cancelled and having their tasks stopped.
            for job, _ in cancelled_jobs:
                task = self._running_jobs.get(job.id)
                if task is not None and not task.done():
                    task.cancel()
                    tasks.append(task)

        if tasks:
            await asyncio.gather(
                *(asyncio.shield(task) for task in tasks), return_exceptions=True
            )

        for job, title in cancelled_jobs:
            self._settle(job.id, "the download was cancelled", cancelled=True)
            await self._events.publish(job, DownloadStatus.CANCELLED, title=title)

    async def cancel_watch(self, watch: DownloadWatch) -> None:
        """Cancel all unsettled download jobs tracked by this watch."""
        await self.cancel_jobs(watch.active_job_ids)

    def _settle(
        self,
        job_id: str,
        error: str | None = None,
        *,
        unchanged: bool = False,
        cancelled: bool = False,
    ) -> None:
        """Tell whoever is watching how one job ended.

        The first outcome a job reports wins: a settled job is no longer
        tracked, so the backstop in :meth:`process_job` speaks only for one
        that ended without saying anything.
        """
        for watch in self._watches:
            watch.settle(job_id, error, unchanged=unchanged, cancelled=cancelled)

    async def backlog_page(self, after: str | None, limit: int) -> DownloadJobsPage:
        """Return one page of queued and running jobs, after the job *after*."""
        async with self._database.read_session() as session:
            rows = await DownloadJobRepository(session).list_active_with_titles(
                after=after, limit=limit + 1
            )
        return DownloadJobsPage(
            items=self._events.snapshot_from_jobs(rows[:limit]),
            next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
        )

    async def snapshot_events(self) -> list[DownloadJobEvent]:
        """Return queued/running events for reconnect snapshots."""
        async with self._database.read_session() as session:
            jobs = await DownloadJobRepository(session).list_active_with_titles(
                running_only=True, limit=sum(self._lane_sizes.values())
            )
        return self._events.snapshot_from_jobs(jobs)

    @staticmethod
    def _worker_done(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.error(
                "A download lane stopped: its jobs could not be saved",
                exc_info=failure,
            )

    async def _recover_jobs(self) -> None:
        """Reconcile interrupted jobs before workers may claim rows.

        A job left running was cut off; a job holding a write intent was cut
        off while replacing a file or uploading a theme. Every terminal state
        clears the intent, so it marks an interruption and nothing else.
        """
        while True:
            async with self._database.read_session() as session:
                rows = list(
                    (
                        await session.exec(
                            select(DownloadJob)
                            .where(col(DownloadJob.status).in_(ACTIVE_JOB_STATUSES))
                            .where(
                                (col(DownloadJob.status) == JobStatus.RUNNING)
                                | col(DownloadJob.write_intent).is_not(None)
                            )
                            .limit(PAGE_SIZE)
                        )
                    ).all()
                )
            for job in rows:
                try:
                    await self._recover_job(job)
                except (*_JOB_ERRORS, OSError, ValueError, SQLAlchemyError) as exc:
                    logger.exception("Could not recover download %s", job.id)
                    await self.fail_job(
                        job,
                        f"Interrupted download could not be recovered: "
                        f"{public_error_message(exc)}; explicit retry required",
                        title=job.collection_title,
                    )
            if len(rows) < PAGE_SIZE:
                return

    async def _recover_job(self, job: DownloadJob) -> None:
        """Finish, fail or requeue one interrupted job."""
        if job.job_type is JobType.COLLECTION_THEME:
            await verify_collection_upload(
                job,
                provider=self.provider_registry.collections,
                publisher=self._publisher,
                database=self._database,
            )
            return
        async with self._database.read_session() as session:
            current = await selection_state(session, job)
        if job.selection_state is not None and current != job.selection_state:
            raise DownloadError("Download superseded by a newer selection")
        if job.write_intent is not None:
            intent = WriteIntent.model_validate_json(job.write_intent)
            found = await verified_write(self._asset_storage, intent)
            if found is None:
                raise DownloadError("Interrupted replacement could not be verified")
            await self.record_job(job, intent.result, found)
            return
        async with self._database.write_session() as session:
            stored = await session.get(DownloadJob, job.id)
            if stored is not None:
                stored.status = JobStatus.PENDING
                stored.progress_percent = 0
                session.add(stored)

    async def _worker_loop(self, lane: JobType) -> None:
        """Claim durable rows of one lane, sleeping until a commit adds more."""
        wake = self._wake[lane]
        while not self._stopping:
            wake.clear()
            async with self._database.write_session() as session:
                job_id = await DownloadJobRepository(session).claim_pending(
                    _LANES[lane]
                )
            if self._stopping:
                return
            if job_id is None:
                await wake.wait()
                continue
            task = asyncio.create_task(self.process_job(job_id))
            self._running_jobs[job_id] = task
            try:
                await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            finally:
                self._running_jobs.pop(job_id, None)

    async def process_job(self, job_id: str) -> None:
        """Run one download job, and tell any watching run how it ended.

        Settling here as well as in the job itself is what keeps a run that
        is waiting on this job from waiting forever: a job that was cancelled
        before it started, or that failed past the handlers below, still
        reports an outcome.
        """
        try:
            await self._run_job(job_id)
        except Exception as original:
            logger.exception("Download %s failed unexpectedly", job_id)
            try:
                async with self._database.read_session() as session:
                    job = await DownloadJobRepository(session).get(job_id)
                if job is not None and job.status not in {
                    JobStatus.DONE,
                    JobStatus.CANCELLED,
                }:
                    await self.fail_job(job, "Download failed", title=None)
            except Exception:
                logger.exception(
                    "Could not record that download %s failed; stopping its lane",
                    job_id,
                )
                raise RuntimeError(
                    "Download failure persistence unavailable"
                ) from original
        except asyncio.CancelledError:
            self._settle(job_id, "the download was cancelled", cancelled=True)
            raise
        finally:
            self._settle(job_id, "the download did not run")

    async def _run_job(self, job_id: str) -> None:
        """Mark one job, do the work, and record the result.

        The work between the two transactions is a network fetch, a file
        write and a hash - or a YouTube download and a transcode. None of it
        is database work, so none of it happens with the write lock held.
        """
        started = await self._start_job(job_id)
        if started is None:
            return
        job, item = started
        title = _job_title(job, item)

        async def progress(percent: int, stage: str) -> None:
            await self._emit_progress(job, percent, stage, title=title)

        try:
            if job.job_type is JobType.COLLECTION_THEME:
                # The upload is the write: one collection takes one at a time.
                async with self._asset_storage.asset_locks.acquire(
                    f"collection:{job.collection_server_id}"
                ):
                    await upload_collection_theme(
                        job,
                        provider=self.provider_registry.collections,
                        theme_handler=self.theme_handler,
                        progress=progress,
                        publisher=self._publisher,
                        database=self._database,
                    )
                self._settle(job_id)
                await self._events.publish(job, DownloadStatus.COMPLETED, title=title)
                return
            if item is None:
                raise DownloadError("Media item not found")
            if job.job_type is JobType.ART:
                downloaded = await self.art_handler.download(job, item, progress)
            else:
                downloaded = await self.theme_handler.download(job, item, progress)
            # Downloads of one item run side by side; only writing its files
            # takes the item's lock, which sync and refreshes share.
            async with self._asset_storage.asset_locks.acquire(item.id or 0):
                written = await self._save_download(job, item, downloaded)
        except _JOB_ERRORS as exc:
            await self.fail_job(job, exc, title=title)
            return

        if job.status is JobStatus.DONE and written and item.server_item_id:
            try:
                await self.provider_registry.provider.refresh_item(
                    item.server_item_id, unlock=_replaced_assets(job)
                )
            except MediaServerError as exc:
                logger.warning(
                    "Could not refresh %s on the media server: %s", item.title, exc
                )

    async def _start_job(
        self, job_id: str
    ) -> tuple[DownloadJob, MediaItem | None] | None:
        """Mark one job running, and return the rows the work needs."""
        async with self._database.write_session() as session:
            job = await DownloadJobRepository(session).get(job_id)
            if not job or job.status not in ACTIVE_JOB_STATUSES:
                return None

            item: MediaItem | None = None
            if job.job_type is not JobType.COLLECTION_THEME:
                item = (
                    await session.get(MediaItem, job.media_item_id)
                    if job.media_item_id is not None
                    else None
                )
                if item and job.selection_state is None:
                    job.selection_state = await selection_state(session, job)
            if job.job_type is JobType.COLLECTION_THEME or item:
                job.status = JobStatus.RUNNING
                session.add(job)

        if job.job_type is not JobType.COLLECTION_THEME and not item:
            await self.fail_job(job, "Media item not found", title=None)
            return None

        await self._events.publish(
            job, DownloadStatus.STARTED, title=_job_title(job, item)
        )
        return job, item

    async def _save_download(
        self, job: DownloadJob, item: MediaItem, downloaded: PreparedDownload
    ) -> bool:
        """Finish saving before releasing the asset lock, even during shutdown.

        Returns:
            Whether a file was written.
        """
        task = asyncio.create_task(self._commit_download(job, item, downloaded))
        self._committing_jobs[job.id] = task
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            written = task.result()
        finally:
            self._committing_jobs.pop(job.id, None)
        if cancelled:
            raise asyncio.CancelledError
        return written

    async def _commit_download(
        self, job: DownloadJob, item: MediaItem, downloaded: PreparedDownload
    ) -> bool:
        """Replace the file unless it already holds these bytes, then record it.

        Returns:
            Whether a file was written; ``False`` also when the job failed.
        """
        storage = downloaded.storage
        try:
            if not isinstance(downloaded.result, (DownloadedArt, DownloadedTheme)):
                raise DownloadError("Unknown download result")
            data_hash = compute_bytes_hash(downloaded.data)
            await owned_thread(
                storage.validate_target,
                downloaded.target_path,
                downloaded.trusted_root,
            )
            stored = await owned_thread(
                storage.identical_file, downloaded.target_path, data_hash
            )
            if stored is None:
                intent = WriteIntent(
                    target=downloaded.target_path,
                    root=downloaded.trusted_root,
                    file_hash=data_hash,
                    result=downloaded.result,
                )
                async with self._database.write_session() as session:
                    job_row = await session.get(DownloadJob, job.id)
                    if job_row is None or job_row.status is not JobStatus.RUNNING:
                        raise DownloadError("Download is no longer active")
                    if job_row.selection_state != await selection_state(
                        session, job_row
                    ):
                        raise DownloadError("Download superseded by a newer selection")
                    job_row.write_intent = intent.model_dump_json()
                    session.add(job_row)
                written = True
                stored = await storage.write_file_async(
                    downloaded.target_path, downloaded.data, downloaded.trusted_root
                )
            else:
                written = False
                logger.debug(
                    "Download %s is identical to %s; nothing written",
                    job.id,
                    downloaded.target_path,
                )
            await self.record_job(job, downloaded.result, stored)
        except (
            DownloadError,
            PathTraversalError,
            TargetDirectoryMissingError,
            OSError,
            SQLAlchemyError,
            ValueError,
        ) as exc:
            await self.fail_job(job, exc, title=item.title)
            return False
        self._settle(job.id, unchanged=not written)
        await self._events.publish(
            job, DownloadStatus.COMPLETED, title=item.title, unchanged=not written
        )
        if job.media_item_id is not None:
            await emit_library_item_upserted(
                job.media_item_id,
                "download",
                self._publisher,
                database=self._database,
            )
        return written

    async def record_job(
        self, job: DownloadJob, downloaded: DownloadResult, stored: StoredFile
    ) -> None:
        """Store what the download produced and mark the job done."""
        async with self._database.write_session() as session:
            stored_job = await DownloadJobRepository(session).get(job.id)
            item = await session.get(MediaItem, job.media_item_id)
            if not stored_job or not item:
                raise DownloadError("Job or media item went away mid-download")

            if (
                stored_job.selection_state is not None
                and stored_job.selection_state
                != await selection_state(session, stored_job)
            ):
                raise DownloadError("Download superseded by a newer selection")
            await downloaded.record(session, item, stored)
            await auto_unmonitor_completed(session, item)
            stored_job.status = JobStatus.DONE
            stored_job.progress_percent = 100
            stored_job.completed_at = utc_now()
            stored_job.write_intent = None
            stored_job.selection_state = None
            session.add(stored_job)

        job.status = JobStatus.DONE
        job.progress_percent = 100
        job.completed_at = stored_job.completed_at

    async def _emit_progress(
        self,
        job: DownloadJob,
        percent: int,
        stage: str,
        *,
        title: str | None,
    ) -> None:
        """Record how far one job has come, and say so."""
        job.progress_percent = percent
        await self._events.publish(
            job,
            DownloadStatus.PROGRESS,
            title=title,
            percent=percent,
            stage=stage,
        )

    async def fail_job(
        self, job: DownloadJob, error: object, *, title: str | None
    ) -> None:
        """Mark one job failed, forgetting any write it intended, and say so."""
        safe_msg = public_error_message(error)
        completed_at = utc_now()

        async with self._database.write_session() as session:
            stored = await DownloadJobRepository(session).get(job.id)
            if stored:
                stored.write_intent = None
                stored.status = JobStatus.FAILED
                stored.error_message = safe_msg
                stored.completed_at = completed_at
                session.add(stored)

        job.status = JobStatus.FAILED
        job.error_message = safe_msg
        job.completed_at = completed_at
        self._settle(job.id, safe_msg)
        await self._events.publish(
            job, DownloadStatus.FAILED, title=title, error=safe_msg
        )
