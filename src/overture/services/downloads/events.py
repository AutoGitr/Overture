"""Download lifecycle event publishing."""

lazy import logging
lazy from typing import Any

lazy from ... import protocols
lazy from ...db.models.download_job import DownloadJob
lazy from ...domain import JobStatus, JobType
lazy from ...jobs.kinds import DownloadStatus, JobKind
lazy from ...jobs.lifecycle import publish_job_lifecycle
lazy from ...jobs.progress_log import JobOutcome, log_entry
lazy from ...schemas.downloads import DownloadJobEvent
lazy from ...utils.job_events import build_job_payload

logger = logging.getLogger(__name__)


def job_target(job: DownloadJob, title: str | None) -> dict[str, int | str | None]:
    """Return a stable target descriptor for item or collection download events."""
    if job.job_type is JobType.COLLECTION_THEME:
        return {
            "target_type": "collection_theme",
            "collection_server_id": job.collection_server_id,
            "media_type": job.collection_media_type,
            "title": title or job.collection_title,
        }
    return {
        "target_type": "item",
        "media_item_id": job.media_item_id,
        "title": title,
        "season_id": job.season_id,
        "art_type": job.art_type,
        "job_type": job.job_type,
    }


def _download_label(job: DownloadJob, title: str | None) -> str:
    """Name a download the way job logs name their targets."""
    if job.job_type is JobType.COLLECTION_THEME:
        return f"{title or job.collection_title or 'collection'} (collection theme)"
    kind = job.art_type or ("theme" if job.job_type is JobType.THEME else "artwork")
    return f"{title or f'item {job.media_item_id}'} ({kind})"


def _log_outcome(
    job: DownloadJob,
    status: DownloadStatus,
    title: str | None,
    payload: dict[str, Any],
) -> None:
    """Write a finished download's outcome to the container log as one line.

    The download service owns every file write, so a written file is info here
    while the bulk run that queued it mirrors the write at debug.
    """
    if status is DownloadStatus.COMPLETED and payload.get("unchanged"):
        level, outcome = logging.DEBUG, JobOutcome.ADOPTED
        reason = "download is identical to the local file; nothing written"
    elif status is DownloadStatus.COMPLETED:
        level, outcome, reason = logging.INFO, JobOutcome.DOWNLOADED, "written to disk"
    elif status is DownloadStatus.FAILED:
        level, outcome = logging.WARNING, JobOutcome.ERROR
        reason = f"download failed: {payload.get('error') or 'unknown error'}"
    elif status is DownloadStatus.CANCELLED:
        level, outcome, reason = logging.INFO, JobOutcome.SKIPPED, "download cancelled"
    else:
        return
    entry = log_entry(outcome, _download_label(job, title), reason)
    logger.log(level, "Download: %s", entry.format())


class DownloadEventPublisher:
    """Publish download lifecycle events and retain reconnect snapshots."""

    def __init__(self, publisher: protocols.EventPublisher) -> None:
        self._publisher = publisher
        self._active_events: dict[str, DownloadJobEvent] = {}

    def snapshot_from_jobs(
        self,
        jobs: list[tuple[DownloadJob, str]],
    ) -> list[DownloadJobEvent]:
        """Return queued/running jobs, named, merged with live progress events."""
        snapshots = {
            job.id: DownloadJobEvent.model_validate(
                build_job_payload(
                    JobKind.DOWNLOAD,
                    DownloadStatus.PROGRESS
                    if job.status is JobStatus.RUNNING
                    else DownloadStatus.PENDING,
                    event_job_id=job.id,
                    target=job_target(job, title),
                    percent=job.progress_percent,
                    stage=job.status,
                )
            )
            for job, title in jobs
        }
        snapshots.update(
            {
                key: value
                for key, value in self._active_events.items()
                if key in snapshots
            }
        )
        return list(snapshots.values())

    async def publish(
        self,
        job: DownloadJob,
        status: DownloadStatus,
        *,
        title: str | None,
        **payload: Any,
    ) -> None:
        """Publish a typed download lifecycle event.

        The title has no default: every event names the item it is about, and
        a caller that cannot name one says so. A finished download is also
        written to the container log as one outcome line.
        """
        _log_outcome(job, status, title, payload)
        await publish_job_lifecycle(
            JobKind.DOWNLOAD,
            status,
            event_job_id=job.id,
            target=job_target(job, title),
            before_publish=self.remember_job_event,
            publisher=self._publisher,
            **payload,
        )

    def remember_job_event(self, _event: str, payload: dict[str, Any]) -> None:
        """Record one job event in the reconnect projection.

        Called for every published event before it is broadcast, so a browser
        that reconnects mid-download still sees the job it missed.
        """
        job_event = DownloadJobEvent.model_validate(payload)
        if job_event.job.status.running:
            self._active_events[job_event.job.id] = job_event
        else:
            self._active_events.pop(job_event.job.id, None)
