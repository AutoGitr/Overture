"""Download job query helpers."""

lazy from collections.abc import Collection, Iterable
lazy from datetime import datetime

lazy from sqlmodel import col, delete, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.download_job import DownloadJob
lazy from ..db.models.media_item import MediaItem
lazy from ..domain import ACTIVE_JOB_STATUSES, ArtType, JobStatus, JobType, MediaType
lazy from ..services.downloads.queue import AssetScope

#: Statuses a finished job can be in, and therefore safe to age out.
_FINISHED_STATUSES = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)


class DownloadJobRepository:
    """Centralize recurring download-job persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, job_id: str) -> DownloadJob | None:
        """Return a download job by ID."""
        return await self.session.get(DownloadJob, job_id)

    def cancel(
        self, jobs: Iterable[DownloadJob], *, now: datetime, error: str | None = None
    ) -> None:
        """Stage *jobs* as cancelled in this transaction."""
        for job in jobs:
            job.status = JobStatus.CANCELLED
            job.error_message = error
            job.completed_at = now
            self.session.add(job)

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
        scope: AssetScope | None = None,
    ) -> list[tuple[DownloadJob, str]]:
        """Return active jobs in queue order, each with its target's title."""
        stmt = (
            select(
                DownloadJob,
                func.coalesce(
                    col(MediaItem.title), col(DownloadJob.collection_title), ""
                ),
            )
            .outerjoin(MediaItem, col(MediaItem.id) == col(DownloadJob.media_item_id))
            .order_by(col(DownloadJob.created_at), col(DownloadJob.id))
        )
        stmt = stmt.where(col(DownloadJob.status).in_(ACTIVE_JOB_STATUSES))
        if job_ids is not None:
            stmt = stmt.where(col(DownloadJob.id).in_(job_ids))
        if scope is not None:
            if scope.media_item_id is not None:
                stmt = stmt.where(col(DownloadJob.media_item_id) == scope.media_item_id)
            if scope.collection_server_id is not None:
                stmt = stmt.where(
                    col(DownloadJob.collection_server_id) == scope.collection_server_id
                )
            if scope.job_type is not None:
                stmt = stmt.where(col(DownloadJob.job_type) == scope.job_type)
            if scope.art_type is not None:
                stmt = stmt.where(col(DownloadJob.art_type) == scope.art_type)
            if scope.season_id is not None:
                stmt = stmt.where(col(DownloadJob.season_id) == scope.season_id)
        result = await self.session.exec(stmt)
        return [(job, title) for job, title in result.all()]

    async def has_active(self) -> bool:
        """Return whether any queued or running job remains."""
        stmt = (
            select(DownloadJob.id)
            .where(col(DownloadJob.status).in_(ACTIVE_JOB_STATUSES))
            .limit(1)
        )
        return (await self.session.exec(stmt)).first() is not None

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

    async def failed_themes_by_item(
        self, item_ids: list[int] | None = None
    ) -> dict[int, set[str]]:
        """Return the YouTube IDs of failed theme downloads, by media item ID."""
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
        failed: dict[int, set[str]] = {}
        for item_id, url in (await self.session.exec(stmt)).all():
            if item_id is not None and url is not None:
                failed.setdefault(item_id, set()).add(url)
        return failed
