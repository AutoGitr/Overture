"""Assets runs: one pipeline for every asset of titles, seasons and collections.

An art run and a theme run each go through it with their own asset kinds and
sources. Each target gets exactly one decision line, starting with the
outcome it counts under:

* ``Queued`` - a download was created; it replaces what is in place, if anything.
* ``Adopted`` - a source's art is what is already in place, so it is saved as
  the selection and nothing is downloaded.
* ``Skipped`` - nothing to do under the run's options, or what is in place was
  kept, as no source ranked above Current selection replaced it.
* ``No match`` - no usable source had a candidate.
* ``Error`` - no decision could be made.

Downloads report a second line when they settle: ``Downloaded``, ``Skipped``
(cancelled) or ``Error``.
"""

lazy import dataclasses
lazy import logging
lazy from collections.abc import Awaitable, Callable
lazy from contextlib import aclosing
lazy from dataclasses import dataclass, field
lazy from functools import partial

lazy from ...config import Settings
lazy from ...db.ledger import (
    Selection,
    local_file,
    missing_deliveries,
    selection,
)
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.season import Season
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import CURRENT_SELECTION_LABEL, CollectionPosterStyle, ServerAsset
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import BulkAssetTally
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from ...utils.art_urls import public_art_url
lazy from ...utils.concurrency import in_order
lazy from ...utils.text import count_label
lazy from ..art.collection_art import CollectionArtService
lazy from ..art.matcher import ArtMatcher
lazy from ..art.selection import adopt_art
lazy from ..catalog.index import CatalogIndex
lazy from ..downloads.collection_theme import collection_themes_unavailable
lazy from ..downloads.service import DownloadService
lazy from ..downloads.watch import DownloadWatch
lazy from ..library.items import emit_library_item_upserted
lazy from ..local_assets.service import LocalAssets
lazy from ..themes.youtube_resolver import YouTubeResolver
lazy from .plan import (
    Batch,
    RunParams,
    Target,
    checked_recently,
    holds,
    kept_reason,
    plan_run,
)
lazy from .sources import SOURCE_ERRORS, BatchFacts, Decision, Notes, Sources
lazy from .support import (
    DECIDE_CONCURRENCY,
    LEFT_LIBRARY,
    NOT_PUBLIC_ART_URL,
    CheckedStamper,
    queue_and_report,
    queue_download,
    refresh_folder_themes,
    refresh_scope,
    report_downloads,
)

logger = logging.getLogger(__name__)

#: Why a run leaves a target that already holds the art or theme a source chose.
ALREADY_IN_PLACE = "the saved selection is already in place"


@dataclass(frozen=True, slots=True)
class _Keep:
    """A target settled as it is, no source having replaced what it holds."""

    outcome: JobOutcome
    reason: str
    #: What the sources asked to replace it said.
    notes: Notes = field(default_factory=Notes)


@dataclass(frozen=True, slots=True)
class _Restore:
    """A saved selection a required place no longer holds, and no source replaced."""

    saved: Selection
    reason: str
    #: What the sources asked to replace it said.
    notes: Notes = field(default_factory=Notes)


#: What deciding a target found: settled as it is, its saved selection to
#: restore, the sources' decision and notes, or the error that stopped it.
type _Outcome = _Keep | _Restore | tuple[Decision | None, Notes] | Exception


@dataclass(frozen=True, slots=True)
class _Run:
    """Collaborators shared by every target of one run."""

    job: ManagedJob[BulkAssetTally]
    params: RunParams
    sources: Sources
    downloads: DownloadService
    watch: DownloadWatch
    local_assets: LocalAssets
    stamper: CheckedStamper
    app_config: Settings
    database: Database
    #: Why no collection theme can be written, when none can.
    themes_unavailable: str | None

    @property
    def themes(self) -> bool:
        return isinstance(self.params, BulkThemeRequest)

    def queue(
        self,
        target: Target,
        value: str | None,
        *,
        upload_hash: str | None = None,
        poster_style: CollectionPosterStyle | None = None,
    ) -> Callable[[], Awaitable[bool]]:
        """Return how to queue the download that makes *value* the target's asset."""
        return lambda: queue_download(
            target.job(value, upload_hash=upload_hash, poster_style=poster_style),
            planned=selection(target.asset),
            downloads=self.downloads,
            on_queued=self.watch.tracking(target.label),
            database=self.database,
        )


def _count(count: int, *, collections: bool) -> str:
    return count_label(count, "collection asset" if collections else "asset")


async def _load(run: _Run, batch: Batch) -> tuple[list[Target], BatchFacts]:
    """Read one batch's files, then load its targets and what its sources read."""
    owner_ids = list(batch.visits)
    catalog = any(source.catalog for source in run.params.precedence.sources)
    if not batch.collections:
        await run.local_assets.reconcile(
            item_ids=owner_ids,
            art=not run.themes,
            themes=run.themes,
            source="assets.themes" if run.themes else "assets.art",
        )
    async with run.database.read_session() as session:
        failed_themes = DownloadJobRepository(session)
        targets: list[Target] = []
        if batch.collections:
            rows = await CollectionRepository(session).bulk_targets(
                collection_ids=owner_ids, include_unmonitored=True
            )
            index = (
                await CatalogIndex.build_collections(session, rows)
                if catalog
                else CatalogIndex.empty()
            )
            failed = (
                await failed_themes.failed_themes_by_collection(owner_ids)
                if run.themes
                else {}
            )
            targets = [
                Target(row, kind)
                for row in rows
                for kind, _ in batch.visits.get(row.id or 0, ())
            ]
        else:
            # A refresh that completed a title may have unmonitored it; it
            # stays in the run that planned it.
            items = await MediaItemRepository(session).list_bulk_targets(
                item_ids=owner_ids, include_unmonitored=True
            )
            season_owners = [
                item_id
                for item_id, slots in batch.visits.items()
                if any(season_id is not None for _, season_id in slots)
            ]
            seasons: dict[int | None, Season] = {
                season.id: season
                for season in await SeasonRepository(session).list_tracked_for_items(
                    season_owners
                )
            }
            index = (
                await CatalogIndex.build(session, items)
                if catalog
                else CatalogIndex.empty()
            )
            failed = (
                await failed_themes.failed_themes_by_item(owner_ids)
                if run.themes
                else {}
            )
            for item in items:
                for kind, season_id in batch.visits.get(item.id or 0, ()):
                    if season_id is None:
                        targets.append(Target(item, kind))
                    elif season := seasons.get(season_id):
                        targets.append(Target(season, kind, item))
        search_format = (await get_app_settings(session)).theme_search_format
    return targets, BatchFacts(index, failed, search_format)


async def _decide(
    run: _Run, target: Target, *, facts: BatchFacts
) -> tuple[Target, _Outcome]:
    """Decide one target; nothing is reported, and only its files are recorded.

    A target holding a saved selection, or a theme in place, asks only the
    sources ranked above Current selection, and keeps what it holds when none
    of them decides; a saved selection missing from disk is downloaded again.
    Planning already skipped it if it was checked recently, unless it is a
    saved selection to restore, which then asks no source.
    """
    try:
        if (row := target.collection) is not None and target.kind is ServerAsset.THEME:
            if run.themes_unavailable:
                return target, _Keep(JobOutcome.SKIPPED, run.themes_unavailable)
            target = dataclasses.replace(
                target,
                owner=await refresh_folder_themes(
                    row, downloads=run.downloads, database=run.database
                ),
            )
        holding = holds(target.asset)
        sources = run.params.precedence.asked(holding=holding)
        if holding and (
            not sources or checked_recently(target.last_checked, run.params)
        ):
            return target, _kept(target, None)
        decision, notes = await run.sources.ask(target, facts, sources)
        if decision is not None or not holding:
            return target, (decision, notes)
        return target, _kept(target, notes)
    except SOURCE_ERRORS as exc:
        return target, exc


def _kept(target: Target, notes: Notes | None) -> _Keep | _Restore:
    """Keep what a target holds: its saved selection, restored if missing, or theme.

    *notes* are what the sources asked to replace it said, ``None`` when none
    was asked.
    """
    asset = target.asset
    saved = selection(asset)
    said = None if notes is None else "; ".join([*notes.declined, *notes.empty])
    notes = notes or Notes()
    if saved is not None and missing_deliveries(asset):
        reason = _restore_reason(target) + (f"; {said}" if said else "")
        return _Restore(saved, reason, notes)
    return _Keep(
        JobOutcome.SKIPPED, kept_reason(saved=saved is not None, said=said), notes
    )


async def _stamp(run: _Run, target: Target) -> None:
    """Record that the target's owner was checked, for the skip-recent window."""
    owner, title = target.owner, target.title
    try:
        if isinstance(owner, MediaCollection):
            await run.stamper.add(collection_id=owner.id)
        else:
            await run.stamper.add(
                item_id=title.id if title else None,
                season_id=owner.id if isinstance(owner, Season) else None,
            )
    except SOURCE_ERRORS as exc:
        await run.job.report(
            JobOutcome.ERROR,
            target.label,
            f"could not record the check time: {exc}",
            finished=False,
        )


def _restore_reason(target: Target) -> str:
    if target.collection is not None:
        return "restores the saved selection"
    missing = (
        "missing" if local_file(target.asset) is None else "replaced outside Overture"
    )
    return f"restores the saved selection; local file {missing}"


async def _adopt(run: _Run, target: Target, decision: Decision) -> None:
    """Save a source's art as the selection of what is in place, and report it."""
    job = run.job
    art_type = target.kind.art_type
    if art_type is None:
        raise ValueError("Only artwork is adopted")
    url = await public_art_url(decision.value, app_config=run.app_config)
    if url is None:
        await job.report(JobOutcome.SKIPPED, target.label, NOT_PUBLIC_ART_URL)
        return
    if (row := target.collection) is not None:
        if run.sources.art is None:
            raise ValueError("Collection art runs adopt through collection art")
        await run.sources.art.adopt(row.id or 0, art_type, url, decision.poster_style)
        sent = "nothing uploaded"
    else:
        title = target.title
        if title is None or title.id is None or decision.verified is None:
            raise ValueError("A title's art is adopted for a verified local file")
        if not await adopt_art(
            title.id,
            art_type,
            season_id=target.owner.id if isinstance(target.owner, Season) else None,
            url=url,
            verified=decision.verified,
            asset_storage=run.local_assets.asset_storage,
            database=run.database,
        ):
            await job.report(
                JobOutcome.SKIPPED,
                target.label,
                "the local file changed while it was being compared; "
                "it is checked again on the next run",
            )
            return
        await emit_library_item_upserted(
            title.id, "assets.art", job.context.publisher, database=run.database
        )
        sent = "nothing downloaded"
    await job.report(
        JobOutcome.ADOPTED, target.label, f"{decision.reason}; selection saved, {sent}"
    )
    await _stamp(run, target)


async def _source_errors(run: _Run, target: Target, notes: Notes) -> None:
    """Report each source that failed before the target was decided, on its own line."""
    for error in notes.errors:
        await run.job.report(JobOutcome.ERROR, target.label, error, finished=False)


async def _act(run: _Run, target: Target, decision: Decision, notes: Notes) -> None:
    """Adopt or queue what a source decided, and report it."""
    job = run.job
    await _source_errors(run, target, notes)
    asset = target.asset
    saved = selection(asset)
    if (
        saved is not None
        and (saved.url or saved.youtube_id) == decision.value
        and not missing_deliveries(asset)
    ):
        await job.report(JobOutcome.SKIPPED, target.label, ALREADY_IN_PLACE)
        await _stamp(run, target)
        return
    if decision.adopt:
        await _adopt(run, target, decision)
        return
    if await queue_and_report(
        job,
        target.label,
        decision.reason,
        run.queue(target, decision.value, poster_style=decision.poster_style),
    ):
        await _stamp(run, target)


async def _undecided(run: _Run, target: Target, notes: Notes) -> None:
    """Report a target no source decided, keeping what is in place."""
    if notes.declined:
        await run.job.report(
            JobOutcome.SKIPPED,
            target.label,
            f"kept the local file: {notes.text()} (ranking OvertureDB above "
            f"{CURRENT_SELECTION_LABEL} would replace it)",
        )
    elif notes.errors:
        await run.job.report(JobOutcome.ERROR, target.label, notes.text())
        return
    else:
        await run.job.report(JobOutcome.NO_MATCH, target.label, notes.text())
    await _stamp(run, target)


async def _visit(run: _Run, target: Target, outcome: _Outcome) -> None:
    """Report and act on one decided target, never failing the batch."""
    job = run.job
    try:
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, _Keep | _Restore):
            await _source_errors(run, target, outcome.notes)
        if isinstance(outcome, _Keep):
            await job.report(outcome.outcome, target.label, outcome.reason)
        elif isinstance(outcome, _Restore):
            saved = outcome.saved
            await queue_and_report(
                job,
                target.label,
                outcome.reason,
                run.queue(
                    target,
                    saved.url or saved.youtube_id,
                    upload_hash=saved.upload_hash,
                    poster_style=target.asset.poster_style,
                ),
            )
        elif (decision := outcome[0]) is None:
            await _undecided(run, target, outcome[1])
        else:
            await _act(run, target, decision, outcome[1])
    except SOURCE_ERRORS as exc:
        # The entry logs the error; its traceback is detail.
        logger.debug("Assets decision for %s failed", target.label, exc_info=exc)
        await job.report(JobOutcome.ERROR, target.label, str(exc))


async def _run(
    context: JobContext,
    params: RunParams,
    sources: Sources,
    *,
    downloads: DownloadService,
    local_assets: LocalAssets,
    app_config: Settings,
    database: Database,
) -> None:
    """Plan the whole run, then visit its targets a batch at a time.

    The total is fixed before the first target is visited; only planned
    visits have their files read and their sources asked.
    """
    themes = isinstance(params, BulkThemeRequest)
    with downloads.watch() as watch:
        async with run_managed_job(context, BulkAssetTally(), database=database) as job:
            run = _Run(
                job=job,
                params=params,
                sources=sources,
                downloads=downloads,
                watch=watch,
                local_assets=local_assets,
                stamper=CheckedStamper(database=database),
                app_config=app_config,
                database=database,
                themes_unavailable=collection_themes_unavailable(
                    downloads.provider_registry.collection_providers()
                )
                if themes
                else None,
            )
            await job.started()
            await refresh_scope(
                params,
                local_assets=local_assets,
                downloads=downloads,
                database=database,
            )
            plan = await plan_run(params, database=database)
            await job.planned(plan.total)
            for (collections, outcome, reason), count in plan.decided.items():
                await job.report(
                    outcome, _count(count, collections=collections), reason, count=count
                )
            async with report_downloads(job, watch, downloads=downloads):
                try:
                    for batch in plan.batches():
                        if job.stop_requested():
                            break
                        targets, facts = await _load(run, batch)
                        planned = sum(len(slots) for slots in batch.visits.values())
                        if missing := planned - len(targets):
                            await job.report(
                                JobOutcome.SKIPPED,
                                _count(missing, collections=batch.collections),
                                LEFT_LIBRARY,
                                count=missing,
                            )
                        # Sources are asked for a few targets at once; each is
                        # still reported and acted on in plan order.
                        async with aclosing(
                            in_order(
                                targets,
                                partial(_decide, run, facts=facts),
                                limit=DECIDE_CONCURRENCY,
                            )
                        ) as decided:
                            async for target, outcome in decided:
                                if job.stop_requested():
                                    break
                                await _visit(run, target, outcome)
                finally:
                    await run.stamper.flush()


async def run_art(
    context: JobContext,
    params: BulkMatchArtRequest,
    *,
    downloads: DownloadService,
    art_matcher: ArtMatcher,
    art: CollectionArtService,
    local_assets: LocalAssets,
    app_config: Settings,
    database: Database,
) -> None:
    """Run an Assets art job: posters, backgrounds and season posters."""
    await _run(
        context,
        params,
        Sources(params, art_matcher=art_matcher, art=art),
        downloads=downloads,
        local_assets=local_assets,
        app_config=app_config,
        database=database,
    )


async def run_themes(
    context: JobContext,
    params: BulkThemeRequest,
    *,
    downloads: DownloadService,
    youtube_resolver: YouTubeResolver,
    local_assets: LocalAssets,
    app_config: Settings,
    database: Database,
) -> None:
    """Run an Assets theme job, for titles and collections."""
    await _run(
        context,
        params,
        Sources(params, youtube_resolver=youtube_resolver),
        downloads=downloads,
        local_assets=local_assets,
        app_config=app_config,
        database=database,
    )
