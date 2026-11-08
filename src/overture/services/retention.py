"""Age out rows and files nothing reads any more.

Download jobs and items the media server has dropped both accumulate for as
long as Overture runs. Deleting a media item takes its seasons, artwork, values
and download jobs with it through the cascading foreign keys; the values no
title holds any more go after it. Cached images that no artwork slot records
any more go with them.
"""

lazy import logging
lazy from dataclasses import dataclass
lazy from datetime import timedelta

lazy from sqlmodel import col, delete, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.art import ArtSlot
lazy from ..db.models.download_job import DownloadJob
lazy from ..db.models.job_result import JobRun
lazy from ..db.session import Database
lazy from ..domain import JobStatus
lazy from ..repositories.downloads import DownloadJobRepository
lazy from ..repositories.media_items import MediaItemRepository
lazy from ..repositories.terms import TermRepository
lazy from ..utils.time import utc_now
lazy from .storage.image_cache import ImageCache

logger = logging.getLogger(__name__)

#: How long a finished download job stays queryable.
FINISHED_JOB_RETENTION = timedelta(days=30)

#: How long an item the media server dropped is kept before it is deleted.
REMOVED_ITEM_RETENTION = timedelta(days=90)

#: How long a cached image nothing records is kept: long enough that the image
#: of a download or refresh still being recorded is never deleted under it.
UNUSED_IMAGE_RETENTION = timedelta(days=1)


@dataclass(slots=True, frozen=True)
class RetentionResult:
    """What one retention pass deleted."""

    download_jobs: int = 0
    media_items: int = 0
    terms: int = 0

    @property
    def total(self) -> int:
        """Return the number of rows deleted across the sweeps."""
        return self.download_jobs + self.media_items + self.terms


async def prune(session: AsyncSession) -> RetentionResult:
    """Delete aged-out download jobs, long-removed media items and unused values."""
    now = utc_now()
    await session.exec(
        delete(JobRun).where(col(JobRun.finished_at) < now - FINISHED_JOB_RETENTION)
    )
    jobs = await DownloadJobRepository(session).delete_finished_before(
        now - FINISHED_JOB_RETENTION
    )
    items = await MediaItemRepository(session).delete_removed_before(
        now - REMOVED_ITEM_RETENTION
    )
    # The deleted items' values go first, so the terms they held are unused.
    await session.flush()
    return RetentionResult(
        download_jobs=jobs,
        media_items=items,
        terms=await TermRepository(session).prune(),
    )


async def prune_image_cache(*, database: Database, image_cache: ImageCache) -> int:
    """Delete the cached images nothing records, once they are old enough.

    A slot records its file and its uploaded selection; a queued download, the
    upload it will write.

    Returns:
        How many cached files were deleted.
    """
    async with database.read_session() as session:
        files = await session.exec(
            select(ArtSlot.file_hash).where(col(ArtSlot.file_hash).is_not(None))
        )
        uploads = await session.exec(
            select(ArtSlot.upload_hash).where(col(ArtSlot.upload_hash).is_not(None))
        )
        queued = await session.exec(
            select(DownloadJob.upload_hash).where(
                col(DownloadJob.upload_hash).is_not(None),
                col(DownloadJob.status).in_((JobStatus.PENDING, JobStatus.RUNNING)),
            )
        )
        recorded = {file_hash for file_hash in (*files, *uploads, *queued) if file_hash}
    return await image_cache.prune(
        recorded,
        older_than=(utc_now() - UNUSED_IMAGE_RETENTION).timestamp(),
    )


async def run_retention_pass(
    *, database: Database, image_cache: ImageCache
) -> RetentionResult:
    """Run one retention pass in its own session and log what it removed."""
    async with database.write_session() as session:
        result = await prune(session)
    if images := await prune_image_cache(database=database, image_cache=image_cache):
        logger.info("Retention removed %d cached image files", images)

    if result.total:
        logger.info(
            "Retention removed %d finished downloads, %d removed media items "
            "and %d unused metadata values",
            result.download_jobs,
            result.media_items,
            result.terms,
        )
    return result
