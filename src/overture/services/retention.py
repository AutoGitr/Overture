"""Age out rows nothing reads any more.

Download jobs and items the media server has dropped both accumulate for as
long as Overture runs. Deleting a media item takes its seasons, artwork, and
download jobs with it through the cascading foreign keys, so this whole pass
is two statements.
"""

lazy import logging
lazy from dataclasses import dataclass
lazy from datetime import timedelta

lazy from sqlmodel import col, delete
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.job_result import JobRun
lazy from ..db.session import Database
lazy from ..repositories.downloads import DownloadJobRepository
lazy from ..repositories.media_items import MediaItemRepository
lazy from ..utils.time import utc_now

logger = logging.getLogger(__name__)

#: How long a finished download job stays queryable.
FINISHED_JOB_RETENTION = timedelta(days=30)

#: How long an item the media server dropped is kept before it is deleted.
REMOVED_ITEM_RETENTION = timedelta(days=90)


@dataclass(slots=True, frozen=True)
class RetentionResult:
    """What one retention pass deleted."""

    download_jobs: int = 0
    media_items: int = 0

    @property
    def total(self) -> int:
        """Return the number of rows deleted across both sweeps."""
        return self.download_jobs + self.media_items


async def prune(session: AsyncSession) -> RetentionResult:
    """Delete aged-out download jobs and long-removed media items."""
    now = utc_now()
    await session.exec(
        delete(JobRun).where(col(JobRun.finished_at) < now - FINISHED_JOB_RETENTION)
    )
    result = RetentionResult(
        download_jobs=await DownloadJobRepository(session).delete_finished_before(
            now - FINISHED_JOB_RETENTION
        ),
        media_items=await MediaItemRepository(session).delete_removed_before(
            now - REMOVED_ITEM_RETENTION
        ),
    )
    await session.flush()
    return result


async def run_retention_pass(*, database: Database) -> RetentionResult:
    """Run one retention pass in its own session and log what it removed."""
    async with database.write_session() as session:
        result = await prune(session)

    if result.total:
        logger.info(
            "Retention removed %d finished downloads and %d removed media items",
            result.download_jobs,
            result.media_items,
        )
    return result
