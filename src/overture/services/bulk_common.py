"""Scaffolding shared by the bulk art and bulk theme runners.

Both plan their whole run before the first decision: every target in scope is
either decided from the database alone, by :func:`planned_outcome`, or kept as
a visit. Only visited targets have their files read and their sources asked,
and the run's total is fixed before any of that starts. Both runners then
stamp ``last_matched_at`` when they are done with a target.
"""

lazy import asyncio
lazy import logging
lazy from collections import Counter
lazy from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass, field
lazy from datetime import datetime, timedelta
lazy from itertools import batched
lazy from typing import Any, Protocol

lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.art_slots import read_art_slot
lazy from ..db.models.media_item import MediaItem
lazy from ..db.session import CHUNK_SIZE, PAGE_SIZE, Database
lazy from ..domain import MediaSortKey, RecentUnit, media_sort_key
lazy from ..jobs.progress_log import JobOutcome
lazy from ..jobs.runner import ManagedJob
lazy from ..jobs.tally import BulkAssetTally
lazy from ..repositories.media_items import MediaItemRepository
lazy from ..repositories.seasons import SeasonRepository
lazy from ..utils.errors import public_error_message
lazy from ..utils.time import utc_now
lazy from .downloads.queue import JobTarget
lazy from .downloads.service import DownloadService
lazy from .downloads.watch import DownloadWatch

logger = logging.getLogger(__name__)

#: Targets whose sources are asked at once. Asking mostly waits on image
#: downloads or a yt-dlp search, so a few overlap without flooding providers.
DECIDE_CONCURRENCY = 4

#: Why targets with a saved selection were not visited.
SAVED_SELECTION = (
    "saved selection already set; Retry saved downloads restores missing files "
    "and Overwrite existing searches again"
)

#: Why planned targets could not be visited: their row left the library.
LEFT_LIBRARY = "no longer in the library"

#: What one target came to without being visited: its outcome and the reason.
type PlannedOutcome = tuple[JobOutcome, str]


class AssetRunParams(Protocol):
    """The options of a bulk request that decide targets while planning."""

    overwrite_existing: bool
    retry_saved_downloads: bool
    library_ids: list[str]
    item_ids: list[int] | None
    include_unmonitored: bool
    skip_recent_val: int
    skip_recent_unit: RecentUnit


def planned_outcome(
    params: AssetRunParams,
    *,
    saved: bool,
    last_checked: datetime | None,
    in_catalog: bool | None,
    no_catalog: str,
) -> PlannedOutcome | None:
    """Decide one target from the database, or return ``None`` to visit it.

    This is the planning half of an Assets decision; a visit makes the half
    that needs the files on disk or a source. *in_catalog* is ``None`` unless
    the run's sole sources are datasets, and then says whether one of them
    serves the target.
    The rules apply in order:

    1. A saved selection is skipped unless Retry or Overwrite is on.
    2. On a dataset-only run, a target no dataset serves is no match, unless
       it is a saved selection Retry may restore.
    3. A saved selection Retry may restore is visited, whenever last checked.
    4. A target checked within the Skip recently checked window is skipped.
    5. Everything else is visited.
    """
    restores = saved and not params.overwrite_existing
    if restores and not params.retry_saved_downloads:
        return JobOutcome.SKIPPED, SAVED_SELECTION
    if in_catalog is False and not restores:
        return JobOutcome.NO_MATCH, no_catalog
    if restores:
        return None
    if checked_recently(last_checked, params):
        return (
            JobOutcome.SKIPPED,
            f"checked within the last {recent_window_label(params)}",
        )
    return None


@dataclass(slots=True, frozen=True)
class AssetPlan[TargetT]:
    """Every target of one bulk run: decided while planning, or to visit.

    Visits hold IDs rather than rows, so a plan for the whole library stays
    small; each batch's rows are loaded, and its files read, when it is
    visited.
    """

    decided: Counter[PlannedOutcome] = field(default_factory=Counter[PlannedOutcome])
    _visits: list[tuple[MediaSortKey, int, tuple[TargetT, ...]]] = field(
        default_factory=list[tuple[MediaSortKey, int, tuple[TargetT, ...]]]
    )

    def decide(self, outcome: PlannedOutcome) -> None:
        """Count one target decided while planning."""
        self.decided[outcome] += 1

    def visit(self, item: MediaItem, targets: list[TargetT]) -> None:
        """Keep *item*'s *targets* for a visit, in the order they are given."""
        if targets and item.id is not None:
            key = media_sort_key(item.media_type, item.title, item.id)
            self._visits.append((key, item.id, tuple(targets)))

    @property
    def total(self) -> int:
        """Return how many targets the run reports on, decided or visited."""
        return self.decided.total() + sum(len(t) for _, _, t in self._visits)

    def batches(self) -> Iterator[dict[int, tuple[TargetT, ...]]]:
        """Yield the visits a batch at a time, movies then shows by title."""
        for batch in batched(sorted(self._visits), PAGE_SIZE, strict=False):
            yield {item_id: targets for _, item_id, targets in batch}


async def report_planned[TallyT: BulkAssetTally](
    job: ManagedJob[TallyT],
    plan: AssetPlan[Any],
    label: Callable[[int], str],
) -> None:
    """Fix the run's total and report what planning decided, one line a reason."""
    await job.planned(plan.total)
    for (outcome, reason), count in plan.decided.items():
        await job.report(outcome, label(count), reason, count=count)


async def report_unloaded[TallyT: BulkAssetTally](
    job: ManagedJob[TallyT],
    batch: dict[int, tuple[Any, ...]],
    loaded: int,
    label: Callable[[int], str],
) -> None:
    """Count planned targets whose rows could not be loaded, so none go missing."""
    if missing := sum(len(targets) for targets in batch.values()) - loaded:
        await job.report(JobOutcome.ERROR, label(missing), LEFT_LIBRARY, count=missing)


async def queue_and_report[TallyT: BulkAssetTally](
    job: ManagedJob[TallyT],
    target: str,
    reason: str,
    queue: Callable[[], Awaitable[bool]],
) -> bool:
    """Queue one download and log what happened to it.

    Returns:
        Whether the target ended with a download queued, by this run or an
        identical earlier request.
    """
    try:
        created = await queue()
    except SelectionChangedError:
        await job.report(
            JobOutcome.SKIPPED,
            target,
            f"{reason}; not queued: the selection changed during the run",
        )
        return False
    except (SQLAlchemyError, OSError, ValueError) as exc:
        await job.report(
            JobOutcome.ERROR,
            target,
            f"could not queue the download ({reason}): {public_error_message(exc)}",
        )
        return False
    if created:
        await job.report(JobOutcome.QUEUED, target, reason)
    else:
        await job.report(
            JobOutcome.SKIPPED,
            target,
            f"{reason}; an identical download is already queued or running",
        )
    return True


def recent_window_label(params: AssetRunParams) -> str:
    """Name the skip-recent window the way the user set it."""
    unit = params.skip_recent_unit.value.removesuffix("s")
    plural = "" if params.skip_recent_val == 1 else "s"
    return f"{params.skip_recent_val} {unit}{plural}"


def checked_recently(last_checked: datetime | None, params: AssetRunParams) -> bool:
    """Return whether *last_checked* falls inside the skip-recent window."""
    if params.skip_recent_val <= 0 or last_checked is None:
        return False
    window = timedelta(seconds=params.skip_recent_val * params.skip_recent_unit.seconds)
    return utc_now() - last_checked < window


def count_label(count: int, noun: str) -> str:
    """Return *count* with *noun*, pluralised."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


async def scope_chunks(
    params: AssetRunParams, *, database: Database, chunk: int = CHUNK_SIZE
) -> AsyncGenerator[tuple[AsyncSession, list[MediaItem]]]:
    """Yield the run's scope a chunk of items at a time, by ID.

    Each chunk comes with the read session it was loaded in, for the caller's
    lookups about the same items.
    """
    after_id = 0
    while True:
        async with database.read_session() as session:
            items = await MediaItemRepository(session).list_bulk_targets(
                params.library_ids,
                item_ids=params.item_ids,
                include_unmonitored=params.include_unmonitored,
                after_id=after_id,
                limit=chunk,
            )
            yield session, items
        if len(items) < chunk:
            return
        after_id = max(item.id or 0 for item in items)


class SelectionChangedError(Exception):
    """The slot no longer holds the selection a run planned its download with."""


async def _holds_selection(
    session: AsyncSession, target: JobTarget, planned: str | None
) -> bool:
    """Return whether *target*'s slot still holds the *planned* selection."""
    item = await session.get(MediaItem, target.media_item_id)
    if item is None:
        return False
    if target.art_type is None:
        return item.youtube_id == planned
    owner = await SeasonRepository(session).art_owner(
        item, target.art_type, target.season_id
    )
    return owner is not None and read_art_slot(owner, target.art_type).url == planned


async def queue_download(
    target: JobTarget,
    *,
    planned: str | None,
    downloads: DownloadService,
    on_queued: Callable[[str], None],
    database: Database,
) -> bool:
    """Queue one download in a transaction of its own; return whether it is new.

    *planned* is the slot's saved selection when the run decided on *target*.

    Raises:
        SelectionChangedError: When the slot's selection changed since, or its item
            left the library: a newer choice is not superseded by the run's.
    """
    async with (
        downloads.asset_locks.acquire(target.slot.lock_key),
        database.write_session() as session,
    ):
        if not await _holds_selection(session, target, planned):
            raise SelectionChangedError
        job_id, created = await downloads.queue_job(session, target)
    if created:
        on_queued(job_id)
    await downloads.committed(session)
    return created


@asynccontextmanager
async def report_downloads[TallyT: BulkAssetTally](
    job: ManagedJob[TallyT],
    watch: DownloadWatch,
    *,
    downloads: DownloadService,
) -> AsyncGenerator[None]:
    """Report downloads concurrently while the caller queues more work.

    Closing the context says matching is over. The reporter then stays alive
    until the last queued download settles, so completion means every file
    is on disk, identical already, or reported as failed.
    """

    async def publish() -> None:
        async for outcome in watch.stream():
            job.tally.settled += 1
            if outcome.cancelled:
                await job.report(
                    JobOutcome.SKIPPED,
                    outcome.target,
                    "download cancelled before it finished",
                    finished=False,
                )
            elif outcome.error:
                await job.report(
                    JobOutcome.ERROR,
                    outcome.target,
                    f"download failed: {outcome.error}",
                    finished=False,
                )
            elif outcome.unchanged:
                await job.report(
                    JobOutcome.DOWNLOADED,
                    outcome.target,
                    "download is identical to the local file; kept on disk",
                    finished=False,
                )
            else:
                await job.report(
                    JobOutcome.DOWNLOADED,
                    outcome.target,
                    "written to disk",
                    finished=False,
                )
            if job.stop_requested():
                return

    async def monitor_stop() -> None:
        await job.context.stop_event.wait()
        await downloads.cancel_watch(watch)

    reporter = asyncio.create_task(publish())
    stopper = asyncio.create_task(monitor_stop())
    try:
        try:
            yield
        finally:
            watch.close()
            if job.stop_requested():
                job.context.stop_event.set()
            done, _ = await asyncio.wait(
                (reporter, stopper), return_when=asyncio.FIRST_COMPLETED
            )
            if stopper in done or job.stop_requested():
                job.context.stop_event.set()
                await stopper
                # A match already in flight may queue a job after the first
                # cancellation. Matching is now over, so this is the final set.
                await downloads.cancel_watch(watch)
            await reporter
    finally:
        reporter.cancel()
        stopper.cancel()
        await asyncio.gather(reporter, stopper, return_exceptions=True)


class CheckedStamper:
    """Buffers ``last_matched_at`` stamps and writes them a batch at a time.

    Stamping each target as the runner passed it meant a write transaction per
    target - twice per item on a two-art-type run, and once more for each of
    its seasons. Targets accumulate here and leave as one statement per table.
    """

    def __init__(self, *, database: Database) -> None:
        """Start empty, flushing once a batch of targets is buffered."""
        self._database = database
        self._flush_lock = asyncio.Lock()
        self._item_ids: set[int] = set()
        self._season_ids: set[int] = set()

    async def add(self, item_id: int, *, season_id: int | None = None) -> None:
        """Buffer one checked target, flushing when the batch is full."""
        self._item_ids.add(item_id)
        if season_id is not None:
            self._season_ids.add(season_id)
        if len(self._item_ids) + len(self._season_ids) >= CHUNK_SIZE:
            await self.flush()

    async def flush(self) -> None:
        """Write every buffered stamp and start the next batch."""
        async with self._flush_lock:
            if not self._item_ids and not self._season_ids:
                return
            item_ids, self._item_ids = self._item_ids, set()
            season_ids, self._season_ids = self._season_ids, set()
            now = utc_now()
            try:
                async with self._database.write_session() as session:
                    await MediaItemRepository(session).mark_matched(item_ids, now)
                    await SeasonRepository(session).mark_matched(season_ids, now)
            except BaseException:
                self._item_ids.update(item_ids)
                self._season_ids.update(season_ids)
                raise
