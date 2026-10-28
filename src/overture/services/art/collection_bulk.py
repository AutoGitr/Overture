"""Collection poster and background runs, planned like item art.

Collection art lives on the media server, so a chosen image is uploaded at
once rather than queued as a download.
"""

lazy import httpx2

lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.session import Database
lazy from ...domain import ITEM_ART_TYPES, ArtBulkSource, ArtSource, ArtType
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import BulkAssetTally
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.bulk import BulkMatchArtRequest
lazy from ...utils.errors import PublicServiceError, public_error_message
lazy from ...utils.time import utc_now
lazy from ..bulk_common import LEFT_LIBRARY, AssetPlan, count_label, planned_outcome
lazy from .matcher import ArtMatcher
lazy from .service import ArtService

_ERRORS = (PublicServiceError, httpx2.HTTPError, OSError, ValueError)


async def plan_collection_art(
    params: BulkMatchArtRequest, *, database: Database
) -> AssetPlan[ArtType]:
    """Plan every collection slot in scope with the item art skip rules."""
    plan = AssetPlan[ArtType]()
    art_types = [art for art in ITEM_ART_TYPES if art in params.art_types]
    if not params.collection_scope or not art_types:
        return plan
    after = 0
    while True:
        async with database.read_session() as session:
            rows = await CollectionRepository(session).bulk_targets(
                after=after,
                collection_ids=params.collection_ids,
                collection_groups=params.collection_groups,
                include_unmonitored=params.include_unmonitored,
            )
        if not rows:
            return plan
        for row in rows:
            visits: list[ArtType] = []
            for art_type in art_types:
                slot = read_art_slot(row, art_type)
                outcome = planned_outcome(
                    params,
                    saved=slot.url,
                    file_missing=not slot.file_hash,
                    last_checked=row.last_matched_at,
                    catalog=None,
                )
                if outcome is None:
                    visits.append(art_type)
                else:
                    plan.decide(outcome)
            plan.visit(row, visits)
        after = rows[-1].id or after


async def _choose(
    row: MediaCollection,
    art_type: ArtType,
    params: BulkMatchArtRequest,
    *,
    art: ArtService,
    matcher: ArtMatcher,
) -> tuple[JobOutcome, str, str | None]:
    """Return the outcome, its reason and the URL to upload, if any."""
    slot = read_art_slot(row, art_type)
    if slot.url and not params.overwrite_existing:
        return JobOutcome.DOWNLOADED, "restores the saved selection", slot.url
    sources = (
        await art.get_collection_sources(row.id or 0, row.media_type, art_type)
    ).sources
    for source in params.source_order:
        if source is ArtBulkSource.OVERTUREDB:
            if catalog := sources.get(ArtSource.OVERTUREDB):
                return JobOutcome.DOWNLOADED, "OvertureDB art", catalog[0].url
        elif slot.phash:
            comparison = await matcher.match_candidates(
                slot.phash,
                [candidate for found in sources.values() for candidate in found],
                threshold=params.threshold,
                reference_width=slot.width or 0,
            )
            if comparison.matches:
                url = comparison.matches[0].url
                await art.adopt_collection(row.id or 0, row.media_type, art_type, url)
                return JobOutcome.ADOPTED, "matches the server's image", None
    return JobOutcome.NO_MATCH, "no source offered art", None


async def run_collection_art(
    job: ManagedJob[BulkAssetTally],
    params: BulkMatchArtRequest,
    plan: AssetPlan[ArtType],
    *,
    art: ArtService,
    matcher: ArtMatcher,
    database: Database,
) -> None:
    """Visit planned collection slots, uploading what each source chose."""
    for batch in plan.batches():
        if job.stop_requested():
            return
        async with database.read_session() as session:
            rows = await CollectionRepository(session).bulk_targets(
                collection_ids=list(batch), include_unmonitored=True
            )
        loaded = {row.id for row in rows}
        if missing := sum(
            len(targets) for key, targets in batch.items() if key not in loaded
        ):
            await job.report(
                JobOutcome.ERROR,
                count_label(missing, "collection slot"),
                LEFT_LIBRARY,
                count=missing,
            )
        for row in rows:
            for art_type in batch[row.id or 0]:
                if job.stop_requested():
                    return
                target = f"{row.title} ({art_type.value})"
                try:
                    outcome, reason, url = await _choose(
                        row, art_type, params, art=art, matcher=matcher
                    )
                    if url is not None:
                        await art.save_collection(
                            row.id or 0,
                            row.media_type,
                            art_type,
                            SaveArtRequest(url=url),
                        )
                except _ERRORS as exc:
                    await job.report(
                        JobOutcome.ERROR, target, public_error_message(exc)
                    )
                    continue
                await job.report(outcome, target, reason)
            async with database.write_session() as session:
                if stored := await session.get(MediaCollection, row.id):
                    stored.last_matched_at = utc_now()
                    session.add(stored)
