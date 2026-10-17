"""Download job query helpers."""

lazy from collections.abc import Collection
lazy from datetime import datetime

lazy from sqlmodel import col, delete, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.download_job import DownloadJob
lazy from ..db.models.media_item import MediaItem
lazy from ..domain import ACTIVE_JOB_STATUSES, ArtType, JobStatus, JobType, MediaType
lazy from ..services.downloads.queue import JobTarget

#: Statuses a finished job can be in, and therefore safe to age out.
_FINISHED_STATUSES = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)


class DownloadJobRepository:
    """Centralize recurring download-job persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, job_id: str) -> DownloadJob | None:
        """Return a download job by ID."""
        return await self.session.get(DownloadJob, job_id)

    async def find_active_equivalent(self, target: JobTarget) -> DownloadJob | None:
        """Return a queued or running job for the same target.

        A collection takes one theme upload at a time, whatever its source.
        """
        stmt = select(DownloadJob).where(
            col(DownloadJob.job_type) == target.job_type,
            col(DownloadJob.status).in_(ACTIVE_JOB_STATUSES),
        )
        if target.job_type is JobType.COLLECTION_THEME:
            stmt = stmt.where(
                col(DownloadJob.collection_server_id) == target.collection_server_id
            )
        else:
            stmt = stmt.where(
                col(DownloadJob.media_item_id) == target.media_item_id,
                col(DownloadJob.art_type) == target.art_type,
                col(DownloadJob.target_url) == target.target_url,
                col(DownloadJob.season_id) == target.season_id,
            )
        return (await self.session.exec(stmt)).first()

    def create(
        self,
        *,
        job_type: JobType,
        target_url: str,
        created_at: datetime,
        media_item_id: int | None = None,
        art_type: ArtType | None = None,
        season_id: int | None = None,
        collection_server_id: str | None = None,
        collection_media_type: MediaType | None = None,
        collection_title: str | None = None,
    ) -> DownloadJob:
        """Create and stage a new download job."""
        job = DownloadJob(
            media_item_id=media_item_id,
            job_type=job_type,
            art_type=art_type,
            target_url=target_url,
            season_id=season_id,
            collection_server_id=collection_server_id,
            collection_media_type=collection_media_type,
            collection_title=collection_title,
            created_at=created_at,
        )
        self.session.add(job)
        return job

    async def list_active_with_titles(
        self,
        *,
        job_ids: Collection[str] | None = None,
        after: str | None = None,
        limit: int | None = None,
        running_only: bool = False,
    ) -> list[tuple[DownloadJob, str]]:
        """Return queued or running jobs, each with the title of its target."""
        stmt = (
            select(
                DownloadJob,
                func.coalesce(
                    col(MediaItem.title), col(DownloadJob.collection_title), ""
                ),
            )
            .outerjoin(MediaItem, col(MediaItem.id) == col(DownloadJob.media_item_id))
            .where(col(DownloadJob.status).in_(ACTIVE_JOB_STATUSES))
            .order_by(col(DownloadJob.id))
        )
        if after is not None:
            stmt = stmt.where(col(DownloadJob.id) > after)
        if limit is not None:
            stmt = stmt.limit(limit)
        if running_only:
            stmt = stmt.where(col(DownloadJob.status) == JobStatus.RUNNING)
        if job_ids is not None:
            stmt = stmt.where(col(DownloadJob.id).in_(job_ids))
        result = await self.session.exec(stmt)
        return [(job, title) for job, title in result.all()]

    async def claim_pending(self, types: tuple[JobType, ...]) -> str | None:
        """Claim one durable job while the caller holds the writer lock."""
        job = (
            await self.session.exec(
                select(DownloadJob)
                .where(
                    col(DownloadJob.status) == JobStatus.PENDING,
                    col(DownloadJob.job_type).in_(types),
                )
                .order_by(col(DownloadJob.created_at), col(DownloadJob.id))
                .limit(1)
            )
        ).first()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        self.session.add(job)
        return job.id

    async def delete_finished_before(self, cutoff: datetime) -> int:
        """Delete jobs that finished before *cutoff* and return the count."""
        result = await self.session.exec(
            delete(DownloadJob).where(
                col(DownloadJob.status).in_(_FINISHED_STATUSES),
                col(DownloadJob.completed_at) < cutoff,
            )
        )
        return result.rowcount or 0

    async def list_failed_theme_targets(
        self, item_ids: list[int] | None = None
    ) -> set[tuple[int, str]]:
        """Return (media_item_id, target_url) pairs for failed theme downloads."""
        stmt = select(
            col(DownloadJob.media_item_id), col(DownloadJob.target_url)
        ).where(
            col(DownloadJob.job_type) == JobType.THEME,
            col(DownloadJob.status) == JobStatus.FAILED,
            col(DownloadJob.media_item_id).is_not(None),
            col(DownloadJob.target_url).is_not(None),
        )
        if item_ids is not None:
            stmt = stmt.where(col(DownloadJob.media_item_id).in_(item_ids))
        result = await self.session.exec(stmt)
        return {
            (item_id, url)
            for item_id, url in result.all()
            if item_id is not None and url is not None
        }
