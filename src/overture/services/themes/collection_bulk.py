"""Catalog-only collection theme planning and downloads."""

lazy from functools import partial

lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.session import Database
lazy from ...db.theme_file import record_theme_file, theme_file_facts
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import BulkAssetTally
lazy from ...media_servers.adapters import FolderThemes
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...schemas.bulk import BulkThemeRequest
lazy from ...utils.errors import public_error_message
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..bulk_common import (
    AssetPlan,
    planned_outcome,
    queue_and_report,
    queue_download,
)
lazy from ..collections.theme_files import collection_folder, inspect_theme_file
lazy from ..downloads.collection_theme import collection_themes_unavailable
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..downloads.watch import DownloadWatch
lazy from ..public_dataset.index import PublicDatasetIndex


async def plan_collection_themes(
    params: BulkThemeRequest, *, app_config: Settings, database: Database
) -> AssetPlan[None]:
    """Plan bounded collection pages using the same skip rules as item themes."""
    plan = AssetPlan[None]()
    if params.collection_ids is None and (
        not params.include_collections or params.item_ids is not None
    ):
        return plan
    after = 0
    while True:
        async with database.read_session() as session:
            rows = await CollectionRepository(session).bulk_targets(
                after=after,
                collection_ids=params.collection_ids,
                library_ids=params.library_ids,
                include_unmonitored=params.include_unmonitored,
            )
            index = await PublicDatasetIndex.build_collections(
                session, rows, app_config=app_config
            )
            failed = await DownloadJobRepository(session).failed_themes_by_collection(
                [row.id for row in rows if row.id is not None]
            )
        if not rows:
            return plan
        for row in rows:
            outcome = planned_outcome(
                params,
                saved=row.youtube_id,
                file_missing=not (row.server_theme_id or row.theme_file_hash),
                last_checked=row.last_matched_at,
                catalog=index.theme(
                    row, params.source_order, failed=failed.get(row.id or 0, set())
                ),
            )
            if outcome is None:
                plan.visit(row, [None])
            else:
                plan.decide(outcome)
        after = rows[-1].id or after


async def _refresh_file(
    row: MediaCollection,
    *,
    downloads: DownloadService,
    app_config: Settings,
    database: Database,
) -> MediaCollection:
    if not isinstance(
        downloads.provider_registry.collections.collections
        if downloads.provider_registry.collections
        else None,
        FolderThemes,
    ):
        return row
    root = app_config.JELLYFIN_COLLECTIONS_PATH
    if root is None or row.server_path is None:
        raise ValueError("The collection theme folder is unavailable")
    async with downloads.asset_locks.acquire(f"collection:{row.id}"):
        async with database.read_session() as session:
            current = await session.get(MediaCollection, row.id)
        if current is None:
            raise ValueError("Collection no longer exists")
        folder = await owned_thread(collection_folder, root, current.server_path or "")
        facts = await owned_thread(
            inspect_theme_file, folder, theme_file_facts(current)
        )
        async with database.write_session() as session:
            if (
                current.theme_file_hash
                and facts
                and current.theme_file_hash != facts.file_hash
            ):
                current.youtube_id = None
                current.youtube_id_source = None
                current.youtube_title = None
                current.youtube_duration = None
            record_theme_file(current, facts)
            session.add(current)
    return current


async def run_collection_themes(
    job: ManagedJob[BulkAssetTally],
    params: BulkThemeRequest,
    plan: AssetPlan[None],
    *,
    downloads: DownloadService,
    watch: DownloadWatch,
    app_config: Settings,
    database: Database,
) -> None:
    """Visit planned collection themes without searching YouTube."""
    reason = collection_themes_unavailable(
        downloads.provider_registry.collections, app_config
    )
    for batch in plan.batches():
        if job.stop_requested():
            return
        async with database.read_session() as session:
            rows = await CollectionRepository(session).bulk_targets(
                collection_ids=list(batch), include_unmonitored=True
            )
            index = await PublicDatasetIndex.build_collections(
                session, rows, app_config=app_config
            )
            failed = await DownloadJobRepository(session).failed_themes_by_collection(
                list(batch)
            )
        if len(rows) < len(batch):
            await job.report(
                JobOutcome.SKIPPED,
                "Collections",
                "no longer in the library",
                count=len(batch) - len(rows),
            )
        for row in rows:
            if job.stop_requested():
                return
            if reason:
                await job.report(JobOutcome.SKIPPED, row.title, reason)
                continue
            try:
                current = await _refresh_file(
                    row, downloads=downloads, app_config=app_config, database=database
                )
            except (OSError, ValueError) as exc:
                await job.report(JobOutcome.ERROR, row.title, public_error_message(exc))
                continue
            has_theme = bool(current.server_theme_id or current.theme_file_hash)
            if not params.overwrite_existing and has_theme:
                await job.report(
                    JobOutcome.SKIPPED, row.title, "kept the installed collection theme"
                )
                continue
            pick = index.theme(
                current, params.source_order, failed=failed.get(row.id or 0, set())
            )
            video = (
                current.youtube_id
                if current.youtube_id and not params.overwrite_existing
                else pick.value
            )
            if not video:
                await job.report(JobOutcome.NO_MATCH, row.title, pick.reason)
                continue
            queue = partial(
                queue_download,
                JobTarget.collection_theme(current.id or 0, current.title, video),
                planned=current.youtube_id,
                downloads=downloads,
                database=database,
                on_queued=watch.tracking(current.title),
            )
            if await queue_and_report(
                job,
                current.title,
                "restores the saved selection"
                if video == current.youtube_id
                else pick.label,
                queue,
            ):
                async with database.write_session() as session:
                    stored = await session.get(MediaCollection, current.id)
                    if stored:
                        stored.last_matched_at = utc_now()
                        session.add(stored)
