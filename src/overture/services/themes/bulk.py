"""Bulk theme runs: decide, per item, which theme to download.

The run is planned before the first visit, as in the artwork runner: items
decided from the database alone are counted in one line per reason, and only
the rest have their theme files read and their sources asked. Each visited
item gets exactly one decision line - ``Queued``, ``Skipped``, ``No match`` or
``Error`` - and each download a second line when it settles.
"""

lazy import logging
lazy from collections.abc import Awaitable, Callable
lazy from contextlib import aclosing
lazy from dataclasses import dataclass, field
lazy from functools import partial

lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import ThemeBulkSource
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import BulkAssetTally
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...schemas.bulk import BulkThemeRequest
lazy from ...utils.concurrency import in_order
lazy from ...utils.errors import public_error_message
lazy from ..bulk_common import (
    DECIDE_CONCURRENCY,
    SAVED_SELECTION,
    AssetPlan,
    CheckedStamper,
    count_label,
    planned_outcome,
    queue_and_report,
    queue_download,
    report_downloads,
    report_unloaded,
    scope_chunks,
)
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..downloads.watch import DownloadWatch
lazy from ..local_assets.service import LocalAssets
lazy from ..public_dataset.index import NO_THEME, PublicDatasetIndex
lazy from .collection_bulk import plan_collection_themes, run_collection_themes
lazy from .youtube_resolver import YouTubeResolver

logger = logging.getLogger(__name__)

#: An item's one planned target: its theme.
type ThemeTarget = None


@dataclass(frozen=True, slots=True)
class BulkThemeWork:
    """One batch of items to visit, and the dataset rows and history for them."""

    items: list[MediaItem]
    search_format: str
    public_index: PublicDatasetIndex = field(default_factory=PublicDatasetIndex.empty)
    #: YouTube IDs that failed to download before, by item ID.
    failed_themes: dict[int, set[str]] = field(default_factory=dict[int, set[str]])


@dataclass(slots=True)
class _Resolution:
    """What asking the sources about one item found."""

    #: The theme to download and why, when a source had one.
    youtube_id: str | None = None
    reason: str = ""
    #: Sources without a candidate, and sources that could not be asked.
    notes: list[str] = field(default_factory=list[str])
    errors: list[str] = field(default_factory=list[str])


@dataclass(frozen=True, slots=True)
class _ThemeRun:
    """Collaborators shared by every item of one run."""

    job: ManagedJob[BulkAssetTally]
    params: BulkThemeRequest
    downloads: DownloadService
    watch: DownloadWatch
    stamper: CheckedStamper
    database: Database

    def queue(self, item: MediaItem, youtube_id: str) -> Callable[[], Awaitable[bool]]:
        """Return how to queue *youtube_id* as the item's theme."""
        item_id = item.id
        if item_id is None:
            raise ValueError("A stored item needs its ID to queue downloads")
        return lambda: queue_download(
            JobTarget.theme(item_id, youtube_id),
            planned=item.youtube_id,
            downloads=self.downloads,
            on_queued=self.watch.tracking(item.title),
            database=self.database,
        )


def _count_label(count: int) -> str:
    return count_label(count, "item")


async def run_bulk_themes(
    context: JobContext,
    params: BulkThemeRequest,
    downloads: DownloadService,
    youtube_resolver: YouTubeResolver,
    *,
    app_config: Settings,
    local_assets: LocalAssets,
    database: Database,
) -> None:
    """Run a bulk theme job in the background.

    The whole run is planned first, so its total is fixed before the first
    item is visited; only planned visits have their theme files read.
    """
    tally = BulkAssetTally()

    with downloads.watch() as watch:
        async with run_managed_job(context, tally, database=database) as job:
            run = _ThemeRun(
                job=job,
                params=params,
                downloads=downloads,
                watch=watch,
                stamper=CheckedStamper(database=database),
                database=database,
            )
            await job.started()
            plan = await plan_bulk_themes(
                params, app_config=app_config, database=database
            )
            collection_plan = await plan_collection_themes(
                params, app_config=app_config, database=database
            )
            await job.planned(plan.total + collection_plan.total)
            for (outcome, reason), count in plan.decided.items():
                await job.report(outcome, _count_label(count), reason, count=count)
            for (outcome, reason), count in collection_plan.decided.items():
                await job.report(
                    outcome, count_label(count, "collection"), reason, count=count
                )
            async with report_downloads(job, watch, downloads=downloads):
                try:
                    for batch in plan.batches():
                        if job.stop_requested():
                            break
                        work = await load_theme_batch(
                            params,
                            list(batch),
                            local_assets=local_assets,
                            app_config=app_config,
                            database=database,
                        )
                        await report_unloaded(job, batch, len(work.items), _count_label)
                        # Sources are asked for a few items at once; each is
                        # still reported and acted on in plan order.
                        async with aclosing(
                            in_order(
                                work.items,
                                partial(
                                    _decide,
                                    params=params,
                                    work=work,
                                    youtube_resolver=youtube_resolver,
                                ),
                                limit=DECIDE_CONCURRENCY,
                            )
                        ) as decided:
                            async for item, outcome in decided:
                                if job.stop_requested():
                                    break
                                await _visit_item(run, item, outcome)
                    await run_collection_themes(
                        job,
                        params,
                        collection_plan,
                        downloads=downloads,
                        watch=watch,
                        app_config=app_config,
                        database=database,
                    )
                finally:
                    await run.stamper.flush()


def _settled_without_sources(item: MediaItem, params: BulkThemeRequest) -> bool:
    """Return whether a saved selection or local file settles the item.

    A saved selection can be new since planning: a refresh adopts the YouTube
    ID embedded in a theme file.
    """
    return not params.overwrite_existing and (
        bool(item.youtube_id) or item.theme_file_hash is not None
    )


async def _settle_existing(run: _ThemeRun, item: MediaItem) -> None:
    """Handle a saved selection or local file when not overwriting."""
    target = item.title
    if saved_id := item.youtube_id:
        if item.theme_file_hash is not None:
            await run.job.report(JobOutcome.SKIPPED, target, SAVED_SELECTION)
        else:
            await queue_and_report(
                run.job,
                target,
                "restores the saved selection; local theme file missing",
                run.queue(item, saved_id),
            )
        return
    await run.job.report(
        JobOutcome.SKIPPED,
        target,
        "kept the local theme file (Replace existing would replace it)",
    )


async def _decide(
    item: MediaItem,
    *,
    params: BulkThemeRequest,
    work: BulkThemeWork,
    youtube_resolver: YouTubeResolver,
) -> tuple[MediaItem, _Resolution | Exception | None]:
    """Ask the enabled sources about one item; nothing is written or reported.

    Planning already skipped it if it was checked recently, unless it is a
    saved selection Retry may restore.

    Returns:
        The item with its sources' answer, ``None`` when a saved selection or
        local file settles it, or the error that stopped the asking.
    """
    if _settled_without_sources(item, params):
        return item, None
    try:
        return item, await _resolve_theme(item, params, work, youtube_resolver)
    except (SQLAlchemyError, OSError, ValueError) as exc:
        return item, exc


async def _visit_item(
    run: _ThemeRun, item: MediaItem, outcome: _Resolution | Exception | None
) -> None:
    """Report and act on one decided item, never failing the batch."""
    item_id = item.id
    if item_id is None:
        return
    target = item.title
    job = run.job
    try:
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            await _settle_existing(run, item)
            return
        if outcome.youtube_id:
            reason = outcome.reason + (
                "; replaces the local theme file"
                if item.theme_file_hash is not None
                else ""
            )
            # A source that failed before this one decided is its own error line.
            for error in outcome.errors:
                await job.report(JobOutcome.ERROR, target, error, finished=False)
            if await queue_and_report(
                job, target, reason, run.queue(item, outcome.youtube_id)
            ):
                await run.stamper.add(item_id)
        elif outcome.errors:
            await job.report(
                JobOutcome.ERROR, target, "; ".join([*outcome.errors, *outcome.notes])
            )
        else:
            await job.report(JobOutcome.NO_MATCH, target, "; ".join(outcome.notes))
            await run.stamper.add(item_id)
    except (SQLAlchemyError, OSError, ValueError) as exc:
        # The entry logs the error; its traceback is detail.
        logger.debug("Theme decision for %s failed", item.title, exc_info=exc)
        await job.report(JobOutcome.ERROR, target, public_error_message(exc))


async def _resolve_theme(
    item: MediaItem,
    params: BulkThemeRequest,
    work: BulkThemeWork,
    youtube_resolver: YouTubeResolver,
) -> _Resolution:
    """Return the first usable YouTube ID in source order, and why others failed."""
    found = _Resolution()
    failed = work.failed_themes.get(item.id or 0, set[str]())
    for source in params.source_order:
        name = source.label
        if source is ThemeBulkSource.YOUTUBE_SEARCH:
            query = (
                work.search_format.replace("{title}", item.title)
                .replace("{year}", str(item.year) if item.year else "")
                .strip()
            )
            try:
                results = await youtube_resolver.search(query, limit=1)
            except (OSError, ValueError) as exc:
                found.errors.append(f"{name}: {public_error_message(exc)}")
                continue
            if not results or not (best_id := results[0].id):
                found.notes.append(f"{name}: no result for {query!r}")
                continue
            if best_id in failed:
                found.notes.append(
                    f"{name}: top result {best_id} failed to download before"
                )
                continue
            title = results[0].title
            found.youtube_id = best_id
            found.reason = f"{name}: {title}" if title else name
            return found
        pick = work.public_index.theme(item, (source,), failed=failed)
        if pick.value is None:
            found.notes.extend(pick.notes)
        else:
            found.youtube_id = pick.value
            found.reason = pick.label
            return found
    return found


async def plan_bulk_themes(
    params: BulkThemeRequest,
    *,
    app_config: Settings,
    database: Database,
    chunk: int = CHUNK_SIZE,
) -> AssetPlan[ThemeTarget]:
    """Plan every item in scope without reading a file or asking a source.

    Items that :func:`planned_outcome` decides are only counted; the rest are
    kept as IDs for :func:`load_theme_batch`.
    """
    dataset_only = all(source.catalog for source in params.source_order)
    plan = AssetPlan[ThemeTarget]()
    # A run over collections alone has no items; libraries may run beside them.
    if params.collection_scope and not params.library_ids:
        return plan
    async with aclosing(scope_chunks(params, database=database, chunk=chunk)) as chunks:
        async for session, items in chunks:
            # Every run reads the catalog: a title it flags has no theme to find.
            index = await PublicDatasetIndex.build(
                session, items, app_config=app_config
            )
            failed_themes = (
                await DownloadJobRepository(session).failed_themes_by_item(
                    [item.id for item in items if item.id is not None]
                )
                if dataset_only
                else {}
            )
            for item in items:
                if index.has_no_theme(item):
                    plan.decide((JobOutcome.SKIPPED, NO_THEME))
                    continue
                decided = planned_outcome(
                    params,
                    saved=item.youtube_id,
                    file_missing=item.theme_file_hash is None
                    and item.folder_path is not None,
                    last_checked=item.last_matched_at,
                    catalog=None
                    if not dataset_only
                    else index.theme(
                        item,
                        params.source_order,
                        failed=failed_themes.get(item.id or 0, set[str]()),
                    ),
                )
                if decided is None:
                    plan.visit(item, [None])
                else:
                    plan.decide(decided)
    return plan


async def load_theme_batch(
    params: BulkThemeRequest,
    item_ids: list[int],
    *,
    local_assets: LocalAssets,
    app_config: Settings,
    database: Database,
) -> BulkThemeWork:
    """Read one batch of planned items' theme files, then load their rows.

    The refresh comes first, so decisions are made against the files on disk,
    including YouTube IDs embedded in them.
    """
    await local_assets.reconcile(
        item_ids=item_ids, art=False, themes=True, source="assets.themes"
    )
    async with database.read_session() as session:
        # A refresh that completed an item may have unmonitored it; it stays in
        # the run that planned it.
        items = await MediaItemRepository(session).list_bulk_targets(
            item_ids=item_ids, include_unmonitored=True
        )
        app_settings = await get_app_settings(session)
        index = (
            await PublicDatasetIndex.build(session, items, app_config=app_config)
            if any(source.catalog for source in params.source_order)
            else PublicDatasetIndex.empty()
        )
        failed_themes = await DownloadJobRepository(session).failed_themes_by_item(
            item_ids
        )
    return BulkThemeWork(items, app_settings.theme_search_format, index, failed_themes)
