"""Bulk artwork runs: decide, per slot, what to download or adopt.

Each visited slot gets exactly one decision line, starting with the outcome
it is counted under:

* ``Queued`` - a download was created; it replaces the local file if any.
* ``Adopted`` - a source's image is byte-identical to the local file, so its
  URL is saved as the selection and nothing is downloaded.
* ``Skipped`` - nothing to do under the run's options, or the local file was
  kept because the source differs and Replace existing is off.
* ``No match`` - no enabled source had a candidate.
* ``Error`` - no decision could be made.

Downloads report a second line when they settle: ``Downloaded``, ``Adopted``
(the download matched the local file), ``Skipped`` (cancelled) or ``Error``.
"""

lazy import logging
lazy from collections.abc import Awaitable, Callable
lazy from contextlib import aclosing
lazy from dataclasses import dataclass, field
lazy from functools import partial

lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...config import Settings
lazy from ...db.art_slots import ArtFileFacts, art_file_facts
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import PERFECT_MATCH_ONLY, ArtBulkSource, ArtType
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import BulkAssetTally
lazy from ...schemas.art import ArtCandidate, ArtMatchResponse
lazy from ...schemas.bulk import BulkMatchArtRequest
lazy from ...utils.concurrency import in_order
lazy from ...utils.errors import public_error_message
lazy from ..bulk_common import (
    DECIDE_CONCURRENCY,
    SAVED_SELECTION,
    CheckedStamper,
    count_label,
    queue_and_report,
    queue_download,
    report_downloads,
    report_unloaded,
)
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..downloads.watch import DownloadWatch
lazy from ..library.items import emit_library_item_upserted
lazy from ..local_assets.service import LocalAssets
lazy from ..public_dataset.index import PublicDatasetIndex
lazy from .bulk_targets import target_art_slot
lazy from .bulk_work import load_art_batch, plan_bulk_art
lazy from .collection_bulk import plan_collection_art, run_collection_art
lazy from .matcher import ArtMatcher
lazy from .selection import adopt_art
lazy from .service import ArtService
lazy from .targets import target_label

logger = logging.getLogger(__name__)

#: Why candidates never reached the comparison stage.
REJECTED_CANDIDATES = "rejected on size or aspect ratio"

#: What the comparison reference was, as said in a reason.
_REFERENCE_NOTES: frozendict[str, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "media_server": "compared with the media server's image",
        "saved_url": "compared with the saved URL's image",
    }
)


@dataclass(frozen=True, slots=True)
class _Decision:
    """What a source decided for a slot."""

    url: str
    reason: str
    #: The local file the URL was verified identical to, for an adoption.
    verified: ArtFileFacts | None = None


@dataclass(slots=True, frozen=True)
class _Notes:
    """Why sources that were tried did not decide."""

    errors: list[str] = field(default_factory=list[str])
    declined: list[str] = field(default_factory=list[str])
    empty: list[str] = field(default_factory=list[str])

    def text(self) -> str:
        return "; ".join([*self.declined, *self.errors, *self.empty])


@dataclass(frozen=True, slots=True)
class _ArtRun:
    """Collaborators shared by every slot of one run."""

    job: ManagedJob[BulkAssetTally]
    params: BulkMatchArtRequest
    downloads: DownloadService
    watch: DownloadWatch
    art_matcher: ArtMatcher
    local_assets: LocalAssets
    stamper: CheckedStamper
    database: Database


def _no_match_reason(match_result: ArtMatchResponse, threshold: int) -> str:
    """Say why local art matching found nothing for one slot."""
    if reason := match_result.reason:
        return reason
    rejected = match_result.prefiltered
    if not match_result.total_compared:
        if rejected == 1:
            return f"1 candidate {REJECTED_CANDIDATES}"
        return (
            f"all {rejected} candidates {REJECTED_CANDIDATES}"
            if rejected
            else "no candidates returned by enabled artwork providers"
        )
    within = (
        "no perfect match"
        if threshold == PERFECT_MATCH_ONLY
        else f"nothing within distance {threshold}"
    )
    return f"{within}, {rejected} {REJECTED_CANDIDATES}" if rejected else within


def _sized(reason: str, candidate: ArtCandidate) -> str:
    """Add the artwork's size to *reason* when its source reported one."""
    if candidate.width and candidate.height:
        return f"{reason}; {candidate.width}x{candidate.height}"
    return reason


async def _from_overturedb(
    run: _ArtRun,
    item: MediaItem,
    art_type: ArtType,
    season: Season | None,
    *,
    local: ArtFileFacts | None,
    index: PublicDatasetIndex,
    notes: _Notes,
) -> _Decision | None:
    pick = index.art(item, art_type, season=season)
    if (url := pick.value) is None:
        notes.empty.extend(pick.notes)
        return None
    if local is None or run.params.overwrite_existing:
        reason = pick.label + ("; replaces the local file" if local else "")
        return _Decision(url, reason)
    try:
        identical = await run.art_matcher.identical_to_local(url, local)
    except ValueError as exc:
        notes.errors.append(f"OvertureDB: {exc}")
        return None
    if identical:
        return _Decision(
            url, "OvertureDB artwork is identical to the local file", verified=local
        )
    notes.declined.append("OvertureDB artwork differs from the local file")
    return None


async def _from_local_matching(
    run: _ArtRun,
    item_id: int,
    art_type: ArtType,
    season_id: int | None,
    *,
    notes: _Notes,
) -> _Decision | None:
    threshold = run.params.threshold
    try:
        outcome = await run.art_matcher.match_item_art(
            item_id=item_id,
            art_type=art_type,
            threshold=max(threshold, 0),
            season_id=season_id,
            include_overturedb=False,
            refresh=False,
        )
    except (SQLAlchemyError, OSError, ValueError) as exc:
        notes.errors.append(f"Local art matching: {public_error_message(exc)}")
        return None
    match_result = outcome.response
    errors = list(match_result.errors)
    if failed := match_result.failed:
        errors.append(f"could not compare {failed} artwork candidates")
    matches = match_result.matches
    if threshold == PERFECT_MATCH_ONLY:
        matches = [match for match in matches if match.perfect_match]
    if not matches:
        if errors:
            notes.errors.append(f"Local art matching: {'; '.join(errors)}")
        else:
            notes.empty.append(
                f"Local art matching: {_no_match_reason(match_result, threshold)}"
            )
        return None

    best = matches[0]
    source = best.source or "an enabled source"
    incomplete = f"; incomplete comparison: {'; '.join(errors)}" if errors else ""
    local = outcome.local_file
    if best.perfect_match and local is not None:
        return _Decision(
            best.url,
            _sized(f"perfect match from {source} is identical to the local file", best)
            + incomplete,
            verified=local,
        )
    reference = match_result.reference
    detail = (
        "replaces the local file"
        if reference == "local_file"
        else _REFERENCE_NOTES.get(reference or "", "")
    )
    reason = _sized(f"d={best.hamming} from {source}", best)
    return _Decision(best.url, reason + (f"; {detail}" if detail else "") + incomplete)


async def _stamp(
    run: _ArtRun, target: str, item_id: int, season_id: int | None
) -> None:
    """Record that the slot was checked, for the skip-recent window."""
    try:
        await run.stamper.add(item_id, season_id=season_id)
    except (SQLAlchemyError, OSError, ValueError) as exc:
        detail = public_error_message(exc)
        await run.job.report(
            JobOutcome.ERROR,
            target,
            f"could not record the check time: {detail}",
            finished=False,
        )


@dataclass(frozen=True, slots=True)
class _Slot:
    """One artwork slot a run visits, with its recorded state."""

    item: MediaItem
    art_type: ArtType
    season: Season | None
    item_id: int
    label: str
    local: ArtFileFacts | None
    saved_url: str | None

    @property
    def target(self) -> str:
        return f"{self.label} ({self.art_type})"

    @property
    def season_id(self) -> int | None:
        return self.season.id if self.season else None

    def queue(self, run: _ArtRun, url: str) -> Callable[[], Awaitable[bool]]:
        return lambda: queue_download(
            JobTarget.art(self.item_id, self.art_type, url, season_id=self.season_id),
            planned=self.saved_url,
            downloads=run.downloads,
            on_queued=run.watch.tracking(self.target),
            database=run.database,
        )

    async def stamp(self, run: _ArtRun) -> None:
        await _stamp(
            run,
            self.target,
            self.item_id,
            self.season_id if self.art_type.owned_by_season else None,
        )


async def _settle_saved(run: _ArtRun, slot: _Slot, saved_url: str) -> None:
    """Keep a saved selection when Replace existing is off, restoring its file."""
    if slot.local is not None:
        await run.job.report(JobOutcome.SKIPPED, slot.target, SAVED_SELECTION)
    else:
        await queue_and_report(
            run.job,
            slot.target,
            "restores the saved selection; local file missing",
            slot.queue(run, saved_url),
        )


async def _resolve(
    run: _ArtRun, slot: _Slot, index: PublicDatasetIndex
) -> tuple[_Decision | None, _Notes]:
    """Try the enabled sources in order until one decides."""
    notes = _Notes()
    for source in run.params.source_order:
        decision = (
            await _from_overturedb(
                run,
                slot.item,
                slot.art_type,
                slot.season,
                local=slot.local,
                index=index,
                notes=notes,
            )
            if source is ArtBulkSource.OVERTUREDB
            else await _from_local_matching(
                run,
                slot.item_id,
                slot.art_type,
                slot.season_id,
                notes=notes,
            )
        )
        if decision is not None:
            return decision, notes
    return None, notes


async def _report_undecided(run: _ArtRun, slot: _Slot, notes: _Notes) -> None:
    """Report a slot no source decided, keeping its local file."""
    if notes.declined:
        await run.job.report(
            JobOutcome.SKIPPED,
            slot.target,
            f"kept the local file: {notes.text()} (Replace existing would replace it)",
        )
    elif notes.errors:
        await run.job.report(JobOutcome.ERROR, slot.target, notes.text())
        return
    else:
        await run.job.report(JobOutcome.NO_MATCH, slot.target, notes.text())
    await slot.stamp(run)


async def _act(run: _ArtRun, slot: _Slot, decision: _Decision, notes: _Notes) -> None:
    """Adopt or queue what a source decided, and report it."""
    job = run.job
    reason = decision.reason
    # A source that failed before this one decided is its own error line.
    for error in notes.errors:
        await job.report(JobOutcome.ERROR, slot.target, error, finished=False)
    if decision.verified is None:
        if await queue_and_report(
            job,
            slot.target,
            reason,
            slot.queue(run, decision.url),
        ):
            await slot.stamp(run)
        return
    if not await adopt_art(
        slot.item_id,
        slot.art_type,
        season_id=slot.season_id,
        url=decision.url,
        verified=decision.verified,
        asset_storage=run.local_assets.asset_storage,
        database=run.database,
    ):
        await job.report(
            JobOutcome.SKIPPED,
            slot.target,
            "the local file changed while it was being compared; "
            "it is checked again on the next run",
        )
        return
    await job.report(
        JobOutcome.ADOPTED,
        slot.target,
        f"{reason}; selection saved, nothing downloaded",
    )
    await emit_library_item_upserted(
        slot.item_id, "assets.art", job.context.publisher, database=run.database
    )
    await slot.stamp(run)


def _slot(
    item: MediaItem, art_type: ArtType, season: Season | None, *, item_id: int
) -> _Slot:
    """Return one slot a run visits, with its recorded state."""
    stored = target_art_slot(item, art_type, season=season)
    return _Slot(
        item=item,
        art_type=art_type,
        season=season,
        item_id=item_id,
        label=target_label(item, season=season),
        local=art_file_facts(stored) if stored else None,
        saved_url=stored.url if stored else None,
    )


#: What deciding a slot found: the sources' decision and notes, the saved URL
#: that settles it without asking them, or the error that stopped the asking.
type _Outcome = tuple[_Decision | None, _Notes] | str | Exception


async def _decide(
    run: _ArtRun, slot: _Slot, *, index: PublicDatasetIndex
) -> tuple[_Slot, _Outcome]:
    """Ask the enabled sources about one slot; nothing is written or reported.

    Planning already skipped it if it was checked recently, unless it is a
    saved selection Retry may restore.
    """
    if slot.saved_url and not run.params.overwrite_existing:
        return slot, slot.saved_url
    try:
        return slot, await _resolve(run, slot, index)
    except (SQLAlchemyError, OSError, ValueError) as exc:
        return slot, exc


async def _visit_slot(run: _ArtRun, slot: _Slot, outcome: _Outcome) -> None:
    """Report and act on one decided slot."""
    if isinstance(outcome, Exception):
        raise outcome
    if isinstance(outcome, str):
        await _settle_saved(run, slot, outcome)
        return
    decision, notes = outcome
    if decision is None:
        await _report_undecided(run, slot, notes)
    else:
        await _act(run, slot, decision, notes)


async def run_bulk_art_match(
    context: JobContext,
    params: BulkMatchArtRequest,
    downloads: DownloadService,
    art_matcher: ArtMatcher,
    *,
    art: ArtService,
    local_assets: LocalAssets,
    app_config: Settings,
    database: Database,
) -> None:
    """Run a bulk artwork job in the background.

    The whole run is planned first, so its total is fixed before the first
    slot is visited; only planned visits have their files read.
    """
    tally = BulkAssetTally()

    with downloads.watch() as watch:
        async with run_managed_job(context, tally, database=database) as job:
            run = _ArtRun(
                job=job,
                params=params,
                downloads=downloads,
                watch=watch,
                art_matcher=art_matcher,
                local_assets=local_assets,
                stamper=CheckedStamper(database=database),
                database=database,
            )
            await job.started()
            plan = await plan_bulk_art(params, app_config=app_config, database=database)
            collection_plan = await plan_collection_art(params, database=database)
            await job.planned(plan.total + collection_plan.total)
            for planned in (plan, collection_plan):
                for (outcome, reason), count in planned.decided.items():
                    await job.report(outcome, _count_label(count), reason, count=count)
            async with report_downloads(job, watch, downloads=downloads):
                try:
                    for batch in plan.batches():
                        if job.stop_requested():
                            break
                        work = await load_art_batch(
                            params,
                            batch,
                            local_assets=local_assets,
                            app_config=app_config,
                            database=database,
                        )
                        await report_unloaded(
                            job, batch, len(work.targets), _count_label
                        )
                        slots = [
                            _slot(item, art_type, season, item_id=item.id)
                            for item, art_type, season in work.targets
                            if item.id is not None
                        ]
                        # Sources are asked for a few slots at once; each is
                        # still reported and acted on in plan order.
                        async with aclosing(
                            in_order(
                                slots,
                                partial(_decide, run, index=work.public_index),
                                limit=DECIDE_CONCURRENCY,
                            )
                        ) as decided:
                            async for slot, outcome in decided:
                                if job.stop_requested():
                                    break
                                try:
                                    await _visit_slot(run, slot, outcome)
                                except (
                                    SQLAlchemyError,
                                    OSError,
                                    ValueError,
                                ) as exc:
                                    # The entry logs the error; its traceback is
                                    # detail.
                                    logger.debug(
                                        "Artwork decision for %s failed",
                                        slot.target,
                                        exc_info=exc,
                                    )
                                    await job.report(
                                        JobOutcome.ERROR,
                                        slot.target,
                                        public_error_message(exc),
                                    )
                    await run_collection_art(
                        job,
                        params,
                        collection_plan,
                        art=art,
                        matcher=art_matcher,
                        database=database,
                    )
                finally:
                    await run.stamper.flush()


def _count_label(count: int) -> str:
    return count_label(count, "art slot")
