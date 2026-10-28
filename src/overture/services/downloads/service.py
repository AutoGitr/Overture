"""Persistent download queue and worker manager."""

lazy import asyncio
lazy import logging
lazy from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Coroutine,
    Generator,
    Iterable,
    Sequence,
)
lazy from contextlib import contextmanager
lazy from dataclasses import dataclass, field
lazy from itertools import batched
lazy from typing import Any

lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import ACTIVE_JOB_STATUSES, JobStatus, JobType, ServerAsset
lazy from ...jobs.gate import LibraryGate
lazy from ...jobs.kinds import INTERRUPTED_MESSAGE, DownloadStatus
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...schemas.downloads import DownloadJobEvent
lazy from ...utils.errors import public_error_message
lazy from ...utils.file import compute_bytes_hash
lazy from ...utils.image import RemoteImageError
lazy from ...utils.locks import KeyedLock
lazy from ...utils.progress import ProgressUpdate
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
lazy from .art import DownloadArtHandler
lazy from .collection_theme import store_collection_theme
lazy from .events import DownloadEventPublisher
lazy from .queue import AssetScope, JobTarget, add_job
lazy from .results import DownloadedCollectionTheme, DownloadResult, PreparedDownload
lazy from .theme import DownloadThemeHandler
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


@dataclass(slots=True)
class _Staged:
    """What one transaction did to the queue, acted on once it commits."""

    lanes: set[JobType] = field(default_factory=set[JobType])
    cancelled: list[tuple[DownloadJob, str]] = field(
        default_factory=list[tuple[DownloadJob, str]]
    )


def _lock_key(job: DownloadJob) -> int | str:
    """Return the asset lock that writing *job*'s asset takes."""
    return AssetScope(job.media_item_id, job.collection_id).lock_key


def _job_title(job: DownloadJob, item: MediaItem | None) -> str | None:
    """Return the name a job's events use for what it writes."""
    if job.job_type is JobType.COLLECTION_THEME:
        return job.collection_title
    return item.title if item else None


class DownloadService:
    """Manage queue lifecycle and worker dispatch."""

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
        library_gate: LibraryGate | None = None,
    ) -> None:
        self._database = database
        self._library_gate = library_gate
        self._gate_release: Callable[[], None] | None = None
        self.art_handler = art_handler
        self.theme_handler = theme_handler
        self.provider_registry = provider_registry
        self._events = events
        self._publisher = publisher
        self._asset_storage = asset_storage
        self._app_config = app_config
        self._lane_sizes = {
            JobType.ART: app_config.ART_DOWNLOAD_WORKERS,
            JobType.THEME: app_config.THEME_DOWNLOAD_WORKERS,
        }
        self._wake = {lane: asyncio.Event() for lane in _LANES}
        self._stopping = False
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._shutdown_task: asyncio.Task[None] | None = None
        self._watches: set[DownloadWatch] = set()
        self._running_jobs: dict[str, asyncio.Task[None]] = {}
        self._committing_jobs: dict[str, asyncio.Task[bool]] = {}

    @property
    def asset_locks(self) -> KeyedLock[int | str]:
        """Locks coordinating access to item and collection assets."""
        return self._asset_storage.asset_locks

    def _hold_gate(self) -> None:
        if self._library_gate is not None and self._gate_release is None:
            self._gate_release = self._library_gate.hold("downloads", "downloads")

    def _release_gate(self) -> None:
        if self._gate_release is not None:
            self._gate_release()
            self._gate_release = None

    async def _reconcile_gate(self) -> None:
        if self._library_gate is None:
            return
        if self._running_jobs:
            self._hold_gate()
            return
        # Serialize the idle decision with enqueue commits, so a new job cannot
        # lose its lease to an older empty-queue observation.
        async with self._database.write_session() as session:
            if await DownloadJobRepository(session).has_active():
                self._hold_gate()
            else:
                self._release_gate()

    def _staged(self, session: AsyncSession) -> _Staged:
        return session.info.setdefault(self, _Staged())

    async def queue_job(
        self, session: AsyncSession, target: JobTarget, *, supersede: bool = True
    ) -> tuple[str, bool]:
        """Add a job for *target* to the caller's transaction.

        An active job for the same source is reused; one for another source is
        cancelled, unless *supersede* is off and it is reused instead. Call
        :meth:`committed` once the transaction commits.

        Returns:
            The job's ID, and whether it is new.
        """
        if self._stopping:
            raise RuntimeError("Downloads are stopping")
        job_id, created, cancelled = await add_job(session, target, supersede=supersede)
        staged = self._staged(session)
        staged.cancelled.extend(cancelled)
        if created:
            staged.lanes.add(_LANE_OF[target.job_type])
        return job_id, created

    async def cancel_assets(self, session: AsyncSession, scope: AssetScope) -> None:
        """Cancel the active jobs writing *scope* in the caller's transaction.

        Call :meth:`committed` once the transaction commits.
        """
        self._cancel(
            session,
            await DownloadJobRepository(session).list_active_with_titles(scope=scope),
        )

    async def cancel_items(
        self,
        session: AsyncSession,
        item_ids: Collection[int],
        job_types: Collection[JobType],
    ) -> None:
        """Cancel the active jobs of *job_types* for any of *item_ids*.

        Call :meth:`committed` once the transaction commits.
        """
        ids = set(item_ids)
        rows = await DownloadJobRepository(session).list_active_with_titles()
        self._cancel(
            session,
            [
                (job, title)
                for job, title in rows
                if job.media_item_id in ids and job.job_type in job_types
            ],
        )

    def _cancel(
        self, session: AsyncSession, rows: list[tuple[DownloadJob, str]]
    ) -> None:
        DownloadJobRepository(session).cancel((job for job, _ in rows), now=utc_now())
        self._staged(session).cancelled.extend(rows)

    async def committed(self, session: AsyncSession) -> None:
        """Act on the jobs *session* queued or cancelled, after it committed."""
        staged: _Staged | None = session.info.pop(self, None)
        if staged is None:
            return
        await self._finish_cancelling(staged.cancelled)
        if staged.lanes:
            self._hold_gate()
            for lane in staged.lanes:
                self._wake[lane].set()

    async def _finish_cancelling(
        self, cancelled: Sequence[tuple[DownloadJob, str]]
    ) -> None:
        """Stop committed cancellations' tasks, then report how they ended."""
        if not cancelled:
            return

        tasks: list[Awaitable[object]] = []
        for job, _ in cancelled:
            task = self._running_jobs.get(job.id)
            if task is not None and not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(
                *(asyncio.shield(task) for task in tasks), return_exceptions=True
            )

        for job, title in cancelled:
            self._settle(job.id, "the download was cancelled", cancelled=True)
            await self._events.publish(job, DownloadStatus.CANCELLED, title=title)
        await self._reconcile_gate()

    async def start(self) -> None:
        """Cancel interrupted downloads and start an empty execution queue."""
        if self._worker_tasks:
            return
        self._stopping = False
        self._shutdown_task = None
        await self._cancel_active_jobs()
        if self._stopping:
            return
        await self._reconcile_gate()
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
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._shutdown_task)

    async def _stop(self) -> None:
        self._stopping = True
        for task in self._worker_tasks:
            task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks.clear()
        await self._cancel_active_jobs()
        self._release_gate()
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
        """Cancel pending or running download jobs by ID.

        A job already saving its file or upload finishes instead.
        """
        ids = set(job_ids)
        if not ids:
            return

        active: list[tuple[DownloadJob, str]] = []
        async with self._database.write_session() as session:
            repository = DownloadJobRepository(session)
            for batch in batched(ids, CHUNK_SIZE, strict=False):
                active += await repository.list_active_with_titles(job_ids=batch)
            # Classify without yielding: a download can start saving while the
            # queries above are awaiting the database.
            saving = [
                commit
                for job, _ in active
                if (commit := self._committing_jobs.get(job.id)) is not None
            ]
            cancelled = [
                (job, title)
                for job, title in active
                if job.id not in self._committing_jobs
            ]
            repository.cancel((job for job, _ in cancelled), now=utc_now())
        if saving:
            await asyncio.gather(
                *(asyncio.shield(commit) for commit in saving), return_exceptions=True
            )
        await self._finish_cancelling(cancelled)

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

    async def snapshot_events(self) -> list[DownloadJobEvent]:
        """Return every queued and running download, for reconnect snapshots."""
        async with self._database.read_session() as session:
            jobs = await DownloadJobRepository(session).list_active_with_titles()
        return self._events.snapshot_from_jobs(jobs)

    @staticmethod
    def _worker_done(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.error(
                "A download lane stopped: its jobs could not be saved",
                exc_info=failure,
            )

    async def _cancel_active_jobs(self) -> None:
        """Cancel any in-flight jobs left from a prior run or during stop."""
        async with self._database.write_session() as session:
            repository = DownloadJobRepository(session)
            cancelled = await repository.list_active_with_titles()
            repository.cancel(
                (job for job, _ in cancelled), now=utc_now(), error=INTERRUPTED_MESSAGE
            )

        for job, title in cancelled:
            self._settle(job.id, INTERRUPTED_MESSAGE, cancelled=True)
            await self._events.publish(
                job, DownloadStatus.CANCELLED, title=title, error=INTERRUPTED_MESSAGE
            )

    async def _worker_loop(self, lane: JobType) -> None:
        """Claim durable rows of one lane, sleeping until a commit adds more."""
        wake = self._wake[lane]
        await wake.wait()
        while not self._stopping:
            wake.clear()
            release = None
            if self._library_gate is not None:
                await self._library_gate.wait_for("downloads")
                # Admission and reservation have no intervening await. Keep
                # sync out while claiming, even before a task is registered.
                release = self._library_gate.hold("downloads", "downloads")
            try:
                async with self._database.write_session() as session:
                    job_id = await DownloadJobRepository(session).claim_pending(
                        _LANES[lane]
                    )
                if self._stopping:
                    return
                if job_id is not None:
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
                await self._reconcile_gate()
            finally:
                if release is not None:
                    release()
            if job_id is None:
                await wake.wait()

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

        async def progress(update: ProgressUpdate) -> None:
            await self._emit_progress(job, update, title=title)

        try:
            if job.job_type is JobType.COLLECTION_THEME:
                downloaded_collection = (
                    await self.theme_handler.download_collection_theme(job, progress)
                )
                # The upload is the write: one collection takes one at a time.
                async with self.asset_locks.acquire(_lock_key(job)):
                    await self._finish_commit(
                        job.id,
                        self._commit_collection_theme(job, downloaded_collection),
                    )
                return
            if item is None:
                raise DownloadError("Media item not found")
            if job.job_type is JobType.ART:
                downloaded = await self.art_handler.download(job, item, progress)
            else:
                downloaded = await self.theme_handler.download(job, item, progress)
            # Downloads of one item run side by side; only writing its files
            # takes the item's lock, which sync and refreshes share.
            async with self.asset_locks.acquire(_lock_key(job)):
                written = await self._finish_commit(
                    job.id, self._commit_download(job, item, downloaded)
                )
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

    async def _finish_commit(
        self, job_id: str, commit: Coroutine[Any, Any, bool]
    ) -> bool:
        """Run a local replacement or remote upload to the end, even when cancelled.

        A cancellation that arrives meanwhile is raised once the commit settled,
        so its outcome is recorded and announced first.
        """
        task = asyncio.create_task(commit)
        self._committing_jobs[job_id] = task
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            written = task.result()
        finally:
            self._committing_jobs.pop(job_id, None)
        if cancelled:
            raise asyncio.CancelledError
        return written

    async def _is_running(self, job_id: str) -> bool:
        """Return whether nothing has ended the job since it started."""
        async with self._database.read_session() as session:
            job = await DownloadJobRepository(session).get(job_id)
        return job is not None and job.status is JobStatus.RUNNING

    async def _commit_download(
        self, job: DownloadJob, item: MediaItem, downloaded: PreparedDownload
    ) -> bool:
        """Replace the file unless it already holds these bytes, then record it.

        Returns:
            Whether a file was written; ``False`` also when the job failed.
        """
        storage = self._asset_storage
        try:
            data_hash = downloaded.file_hash or compute_bytes_hash(downloaded.data)
            await owned_thread(
                storage.validate_target,
                downloaded.target_path,
                downloaded.trusted_root,
            )
            if not await self._is_running(job.id):
                return False
            stored = await owned_thread(
                storage.identical_file, downloaded.target_path, data_hash
            )
            if stored is None:
                written = True
                stored = await storage.write_file_async(
                    downloaded.target_path,
                    downloaded.data,
                    downloaded.trusted_root,
                    file_hash=data_hash,
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

        if job.status is not JobStatus.DONE:
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

    async def _commit_collection_theme(
        self, job: DownloadJob, downloaded: DownloadedCollectionTheme
    ) -> bool:
        """Store the theme on the server unless the job has ended, then record it.

        Returns:
            Whether the theme was stored; ``False`` also when the job failed.
        """
        try:
            if not await self._is_running(job.id):
                return False
            await store_collection_theme(
                job,
                downloaded,
                provider=self.provider_registry.collections,
                asset_storage=self._asset_storage,
                app_config=self._app_config,
                publisher=self._publisher,
                database=self._database,
            )
        except _JOB_ERRORS as exc:
            await self.fail_job(job, exc, title=job.collection_title)
            return False

        if job.status is not JobStatus.DONE:
            return False
        self._settle(job.id)
        await self._events.publish(
            job, DownloadStatus.COMPLETED, title=job.collection_title
        )
        return True

    async def record_job(
        self, job: DownloadJob, downloaded: DownloadResult, stored: StoredFile
    ) -> None:
        """Store what the download produced and mark the job done."""
        async with self._database.write_session() as session:
            stored_job = await DownloadJobRepository(session).get(job.id)
            item = await session.get(MediaItem, job.media_item_id)
            if not stored_job or stored_job.status is not JobStatus.RUNNING or not item:
                return

            await downloaded.record(session, item, stored)
            await auto_unmonitor_completed(session, item)
            stored_job.status = JobStatus.DONE
            stored_job.error_message = None
            stored_job.progress_percent = 100
            stored_job.completed_at = utc_now()
            session.add(stored_job)

        job.status = JobStatus.DONE
        job.error_message = None
        job.progress_percent = 100
        job.completed_at = stored_job.completed_at

    async def _emit_progress(
        self,
        job: DownloadJob,
        update: ProgressUpdate,
        *,
        title: str | None,
    ) -> None:
        """Record how far one job has come, and say so."""
        job.progress_percent = update.percent
        await self._events.publish(
            job,
            DownloadStatus.PROGRESS,
            title=title,
            **update._asdict(),
        )

    async def fail_job(
        self, job: DownloadJob, error: object, *, title: str | None
    ) -> None:
        """Mark one job failed, unless it already ended otherwise."""
        safe_msg = public_error_message(error)
        completed_at = utc_now()

        async with self._database.write_session() as session:
            stored = await DownloadJobRepository(session).get(job.id)
            if stored:
                if stored.status in (JobStatus.CANCELLED, JobStatus.DONE):
                    return
                stored.status = JobStatus.FAILED
                stored.error_message = safe_msg
                stored.completed_at = completed_at
                session.add(stored)

        job.status = JobStatus.FAILED
        job.error_message = safe_msg
        job.completed_at = completed_at
        # The interface names only the title, so the job's ID is here.
        logger.warning(
            "Download %s (%s of %s) failed: %s",
            job.id,
            job.art_type or job.job_type,
            title or "an untitled target",
            safe_msg,
        )
        self._settle(job.id, safe_msg)
        await self._events.publish(
            job, DownloadStatus.FAILED, title=title, error=safe_msg
        )
