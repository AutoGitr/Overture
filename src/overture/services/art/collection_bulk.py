"""Collection poster and background runs, planned like item art.

Collection art lives on the media server, so a chosen image is uploaded at
once rather than queued as a download.
"""

lazy import httpx2
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.session import Database
lazy from ...domain import ITEM_ART_TYPES, PERFECT_MATCH_ONLY, ArtBulkSource, ArtType
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import BulkAssetTally
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.bulk import BulkMatchArtRequest
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..bulk_common import (
    LEFT_LIBRARY,
    NOT_PUBLIC_ART_URL,
    AssetPlan,
    count_label,
    no_match_reason,
    planned_outcome,
)
lazy from ..public_dataset.index import CatalogPick, PublicDatasetIndex
lazy from .collection_art import CollectionArtService

_ERRORS = (PublicServiceError, httpx2.HTTPError, OSError, ValueError)


def _unmatchable(row: MediaCollection, art_type: ArtType) -> str | None:
    """Why local art matching cannot compare a slot, or ``None`` when it can.

    It compares the server's image with the TMDB collection's.
    """
    if row.tmdb_collection_id is None:
        return "Local art matching: the collection has no TMDB collection ID"
    if row.server_item_id is None or row.server_image_url(art_type) is None:
        return "Local art matching: the server has no image to compare"
    return None


def _offer(
    row: MediaCollection,
    art_type: ArtType,
    params: BulkMatchArtRequest,
    index: PublicDatasetIndex,
) -> CatalogPick | None:
    """What decides a slot while planning: the catalog's offer or why nothing can.

    ``None`` leaves a slot some non-catalog source can try to its visit.
    """
    notes: list[str] = []
    for source in params.source_order:
        if source is ArtBulkSource.OVERTUREDB:
            pick = index.collection_art(row, art_type)
            if pick.value is not None:
                return pick if all(s.catalog for s in params.source_order) else None
            notes.extend(pick.notes)
        elif (reason := _unmatchable(row, art_type)) is None:
            return None
        else:
            notes.append(reason)
    return CatalogPick(
        None,
        notes=tuple(notes),
        enabled=index.enabled or not all(s.catalog for s in params.source_order),
    )


async def _index(
    rows: list[MediaCollection],
    params: BulkMatchArtRequest,
    *,
    app_config: Settings,
    session: AsyncSession,
) -> PublicDatasetIndex:
    """OvertureDB's entries for *rows*, read only when the run asks OvertureDB."""
    if ArtBulkSource.OVERTUREDB not in params.source_order:
        return PublicDatasetIndex.empty()
    return await PublicDatasetIndex.build_collections(
        session, rows, app_config=app_config
    )


async def plan_collection_art(
    params: BulkMatchArtRequest, *, app_config: Settings, database: Database
) -> AssetPlan[ArtType]:
    """Plan every collection slot in scope with the item art skip rules.

    Slots no source can serve, such as ones OvertureDB has no entry for on
    a catalog-only run, are decided here and reported together.
    """
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
            index = await _index(rows, params, app_config=app_config, session=session)
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
                    catalog=_offer(row, art_type, params, index),
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
    art: CollectionArtService,
    index: PublicDatasetIndex,
) -> tuple[JobOutcome, str, str | None]:
    """Return the outcome, its reason and the URL to upload, if any."""
    slot = read_art_slot(row, art_type)
    if slot.url and not params.overwrite_existing:
        return JobOutcome.DOWNLOADED, "restores the saved selection", slot.url
    notes: list[str] = []
    for source in params.source_order:
        if source is ArtBulkSource.OVERTUREDB:
            pick = index.collection_art(row, art_type)
            if pick.value is not None:
                return JobOutcome.DOWNLOADED, pick.label, pick.value
            notes.extend(pick.notes)
            continue
        if reason := _unmatchable(row, art_type):
            notes.append(reason)
            continue
        threshold = params.threshold
        result = await art.match(row.id or 0, art_type, max(threshold, 0))
        matches = [
            match
            for match in result.matches
            if threshold != PERFECT_MATCH_ONLY or match.perfect_match
        ]
        if matches:
            if not await art.adopt(row.id or 0, art_type, matches[0].url):
                return JobOutcome.SKIPPED, NOT_PUBLIC_ART_URL, None
            return JobOutcome.ADOPTED, "matches the server's image", None
        notes.append(f"Local art matching: {no_match_reason(result, threshold)}")
    return JobOutcome.NO_MATCH, "; ".join(notes), None


async def run_collection_art(
    job: ManagedJob[BulkAssetTally],
    params: BulkMatchArtRequest,
    plan: AssetPlan[ArtType],
    *,
    art: CollectionArtService,
    app_config: Settings,
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
            index = await _index(rows, params, app_config=app_config, session=session)
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
                        row, art_type, params, art=art, index=index
                    )
                    if url is not None:
                        await art.save(
                            row.id or 0,
                            art_type,
                            SaveArtRequest(url=url),
                        )
                except _ERRORS as exc:
                    await job.report(JobOutcome.ERROR, target, str(exc))
                    continue
                await job.report(outcome, target, reason)
            async with database.write_session() as session:
                if stored := await session.get(MediaCollection, row.id):
                    stored.last_matched_at = utc_now()
                    session.add(stored)
