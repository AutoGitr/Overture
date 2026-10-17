"""Backup WebSocket lifecycle publishing."""

lazy from ... import protocols
lazy from ...jobs.kinds import JobKind
lazy from ...jobs.lifecycle import ManagedJobLifecycle, publish_job_lifecycle
lazy from ...jobs.slot import ManagedBackgroundJob
lazy from ...utils.time import utc_now_iso


class BackupEvents:
    """Own backup lifecycle publishing and snapshot state."""

    def __init__(self, publisher: protocols.EventPublisher) -> None:
        self.job = ManagedBackgroundJob(ManagedJobLifecycle(JobKind.BACKUP), publisher)
        self._publisher = publisher

    async def publish(
        self,
        status: str,
        *,
        scheduled: bool,
        started_at: str | None = None,
        filename: str | None = None,
        error: str | None = None,
        snapshot: bool = False,
    ) -> None:
        """Publish a typed backup lifecycle event."""
        await publish_job_lifecycle(
            JobKind.BACKUP,
            status,
            event_job_id="backup:scheduled" if scheduled else "backup:manual",
            target={"scheduled": scheduled},
            name=f"{'scheduled' if scheduled else 'manual'} backup",
            scheduled=scheduled,
            filename=filename,
            error=error,
            started_at=started_at,
            finished_at=utc_now_iso() if status in {"completed", "failed"} else None,
            save_snapshot=self.job.save_snapshot if snapshot else None,
            publisher=self._publisher,
        )
