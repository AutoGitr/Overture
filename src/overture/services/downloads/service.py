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
lazy from enum import Enum, auto
lazy from functools import partial
lazy from itertools import batched
lazy from typing import Any

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import (
    ACTIVE_JOB_STATUSES,
    AssetScope,
    JobStatus,
    JobType,
    ServerAsset,
)
lazy from ...jobs.kinds import INTERRUPTED_MESSAGE, DownloadStatus
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import Provider, ProviderRegistry
lazy from ...repositories.copies import CopyRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...schemas.art import SaveCollectionArtRequest
lazy from ...schemas.downloads import DownloadJobEvent
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.hashing import compute_bytes_hash
lazy from ...utils.image_fetch import RemoteImageError
lazy from ...utils.locks import KeyedLock
lazy from ...utils.progress import ProgressCallback, ProgressUpdate
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..art.collection_art import CollectionArtService
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
lazy from .queue import JobTarget, add_job, complete_running_job
lazy from .results import (
    DownloadedTheme,
    DownloadResult,
    DownloadTarget,
    PreparedDownload,
)
lazy from .theme import DownloadThemeHandler
lazy from .watch import DownloadWatch

logger = logging.getLogger(__name__)

#: The job types each worker lane drains. Artwork is a short fetch and a file
#: write; a theme is a YouTube download and a transcode that can run for a
#: minute. They are queued apart, and sized apart, so a library's worth of
#: posters cannot end up stuck behind one theme in a single line.
_LANES: frozendict[JobType, tuple[JobType, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        JobType.ART: (JobType.ART, JobType.COLLECTION_ART),
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


#: Errors that fail a job while its content is put in place.
_COMMIT_ERRORS = (
    *_JOB_ERRORS,
    PublicServiceError,
    httpx2.HTTPError,
    OSError,
    SQLAlchemyError,
    ValueError,
)


class _Placed(Enum):
    """How a download's content ended up in place."""

    WRITTEN = auto()
    #: The place already held these bytes, so nothing was written.
    UNCHANGED = auto()
    UPLOADED = auto()


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
    if job.job_type.for_collection:
        return job.collection_title
    return item.title if item else None


class DownloadService:
    """Manage queue lifecycle and worker dispatch."""

    def __init__(
        self,
        *,
        art_handler: DownloadArtHandler,
        theme_handler: DownloadThemeHandler,
        collection_art: CollectionArtService,
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
        self._collection_art = collection_art
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
        self._shutdown_task: asyncio.Task[None] | None = None
        self._watches: set[DownloadWatch] = set()
        self._running_jobs: dict[str, asyncio.Task[None]] = {}
        self._committing_jobs: dict[str, asyncio.Task[bool]] = {}

    @property
    def asset_locks(self) -> KeyedLock[int | str]:
        """Locks coordinating access to item and collection assets."""
        return self._asset_storage.asset_locks

    @property
    def publisher(self) -> protocols.EventPublisher:
        """Publisher announcing completed asset updates."""
        return self._publisher

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

    async def start(self) -> None:
        """Cancel interrupted downloads and start an empty execution queue."""
        if self._worker_tasks:
            return
        self._stopping = False
        self._shutdown_task = None
        await self._cancel_active_jobs()
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
        uploaded: bool = False,
    ) -> None:
        """Tell whoever is watching how one job ended.

        The first outcome a job reports wins: a settled job is no longer
        tracked, so the backstop in :meth:`process_job` speaks only for one
        that ended without saying anything.
        """
        for watch in self._watches:
            watch.settle(
                job_id,
                error,
                unchanged=unchanged,
                cancelled=cancelled,
                uploaded=uploaded,
            )

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

        copies: list[tuple[Provider, str]] = []
        try:
            if job.job_type is JobType.COLLECTION_ART:
                # The upload takes the collection's locks itself.
                await self._finish_commit(
                    job.id,
                    self._commit(
                        job,
                        job.collection_title,
                        partial(self._upload_collection_art, job),
                    ),
                )
                return
            if job.job_type is JobType.COLLECTION_THEME:
                await self._run_collection_theme_job(job, progress)
                return
            if item is None:
                raise DownloadError("Media item not found")
            if job.job_type is JobType.ART:
                downloaded = await self.art_handler.download(job, item, progress)
            else:
                downloaded = await self.theme_handler.download(job, item, progress)
            # Downloads of one item run side by side; only writing its files
            # takes the item's lock, which sync and refreshes share. The item
            # is read again under it, as a sync may have moved its folder.
            async with self.asset_locks.acquire(_lock_key(job)):
                async with self._database.read_session() as session:
                    current = await session.get(MediaItem, item.id)
                if current is None:
                    raise DownloadError("Media item not found")
                item = current
                copies = await self._copies(item)
                target = (
                    await self.art_handler.target(
                        job,
                        item,
                        downloaded,
                        {provider.server_type for provider, _ in copies},
                    )
                    if job.job_type is JobType.ART
                    else self.theme_handler.target(item)
                )
                written = await self._finish_commit(
                    job.id,
                    self._commit(
                        job,
                        item.title,
                        partial(self._write_files, job, downloaded, target),
                    ),
                )
        except _JOB_ERRORS as exc:
            await self.fail_job(job, exc, title=title)
            return

        if job.status is not JobStatus.DONE or not written:
            return
        for provider, server_item_id in copies:
            try:
                await provider.refresh_item(
                    server_item_id, unlock=_replaced_assets(job)
                )
            except MediaServerError as exc:
                logger.warning(
                    "Could not refresh %s on %s: %s",
                    item.title,
                    provider.server.title,
                    exc,
                )

    async def _copies(self, item: MediaItem) -> list[tuple[Provider, str]]:
        """Each configured server holding the item, and its ID of it."""
        async with self._database.read_session() as session:
            copies = await CopyRepository(session).leads_first(item.id or 0)
        return [
            (self.provider_registry.get(copy.server_id), copy.server_item_id)
            for copy in copies
        ]

    async def _start_job(
        self, job_id: str
    ) -> tuple[DownloadJob, MediaItem | None] | None:
        """Mark one job running, and return the rows the work needs."""
        async with self._database.write_session() as session:
            job = await DownloadJobRepository(session).get(job_id)
            if not job or job.status not in ACTIVE_JOB_STATUSES:
                return None

            item: MediaItem | None = None
            if not job.job_type.for_collection:
                item = (
                    await session.get(MediaItem, job.media_item_id)
                    if job.media_item_id is not None
                    else None
                )
            if job.job_type.for_collection or item:
                job.status = JobStatus.RUNNING
                session.add(job)

        if not job.job_type.for_collection and not item:
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

    async def _commit(
        self,
        job: DownloadJob,
        title: str | None,
        place: Callable[[], Awaitable[_Placed]],
    ) -> bool:
        """Put a running job's content in place, record it and announce it.

        The one way every download ends well: *place* writes or uploads the
        content and records the job done through the ledger; a job something
        else ended first is left as it is, and a failure fails the job.

        Returns:
            Whether anything in place changed; ``False`` also when the job
            failed or had already ended.
        """
        try:
            if not await self._is_running(job.id):
                return False
            placed = await place()
        except _COMMIT_ERRORS as exc:
            await self.fail_job(job, exc, title=title)
            return False
        if job.status is not JobStatus.DONE:
            return False
        unchanged = placed is _Placed.UNCHANGED
        self._settle(job.id, unchanged=unchanged, uploaded=placed is _Placed.UPLOADED)
        await self._events.publish(
            job, DownloadStatus.COMPLETED, title=title, unchanged=unchanged
        )
        if job.media_item_id is not None:
            await emit_library_item_upserted(
                job.media_item_id,
                "download",
                self._publisher,
                database=self._database,
            )
        return not unchanged

    async def _write_files(
        self, job: DownloadJob, downloaded: PreparedDownload, target: DownloadTarget
    ) -> _Placed:
        """Write the download into each of a title's paths that lacks these bytes."""
        storage = self._asset_storage
        data_hash = downloaded.file_hash or compute_bytes_hash(downloaded.data)
        for path in target.paths:
            await owned_thread(storage.validate_target, path, target.trusted_root)
        written = False
        recorded: StoredFile | None = None
        for path in target.paths:
            stored = await owned_thread(storage.identical_file, path, data_hash)
            if stored is None:
                written = True
                stored = await storage.write_file_async(
                    path, downloaded.data, target.trusted_root, file_hash=data_hash
                )
            else:
                logger.debug(
                    "Download %s is identical to %s; nothing written", job.id, path
                )
            recorded = recorded or stored
        if recorded is None:
            raise DownloadError("The download has nowhere to go")
        await self.record_job(job, downloaded.result, recorded)
        return _Placed.WRITTEN if written else _Placed.UNCHANGED

    async def _run_collection_theme_job(
        self, job: DownloadJob, progress: ProgressCallback
    ) -> None:
        """Download and deliver one collection theme under the collection lock."""
        prepared = await self.theme_handler.download(job, None, progress)
        if not isinstance(prepared.result, DownloadedTheme):
            raise TypeError("Expected DownloadedTheme for collection theme job")
        # The upload is the write: one collection takes one at a time.
        async with self.asset_locks.acquire(_lock_key(job)):
            await self._finish_commit(
                job.id,
                self._commit(
                    job,
                    job.collection_title,
                    partial(
                        self._upload_collection_theme,
                        job,
                        prepared.data,
                        prepared.result,
                    ),
                ),
            )

    async def _upload_collection_theme(
        self, job: DownloadJob, audio_bytes: bytes, downloaded: DownloadedTheme
    ) -> _Placed:
        """Store the theme on each server copy and record it."""
        await store_collection_theme(
            job,
            audio_bytes,
            downloaded,
            provider_registry=self.provider_registry,
            asset_storage=self._asset_storage,
            publisher=self._publisher,
            database=self._database,
        )
        return _Placed.UPLOADED

    async def _upload_collection_art(self, job: DownloadJob) -> _Placed:
        """Upload the chosen art to each server copy and record it."""
        if job.collection_id is None or job.art_type is None:
            raise DownloadError("The download names no collection slot")
        await self._collection_art.apply(
            job.collection_id,
            job.art_type,
            SaveCollectionArtRequest(
                url=job.target_url,
                upload_hash=job.upload_hash,
                poster_style=job.poster_style,
            ),
        )
        await self._mark_done(job)
        return _Placed.UPLOADED

    async def _mark_done(self, job: DownloadJob) -> None:
        """Mark a running job done once what it writes is recorded."""
        await complete_running_job(self._database, job)

    async def record_job(
        self, job: DownloadJob, downloaded: DownloadResult, stored: StoredFile
    ) -> None:
        """Store what the download produced and mark the job done."""

        async def _record(session: AsyncSession, _now: object) -> bool:
            item = await session.get(MediaItem, job.media_item_id)
            if not item:
                return False
            await downloaded.record(session, item, stored)
            await auto_unmonitor_completed(session, item)
            return True

        await complete_running_job(self._database, job, _record)

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
        safe_msg = str(error)
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
