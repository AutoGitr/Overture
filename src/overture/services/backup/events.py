"""Backup WebSocket lifecycle publishing."""

lazy from ... import protocols
lazy from ...db.session import Database
lazy from ...jobs.kinds import JobKind
lazy from ...jobs.lifecycle import ManagedJobLifecycle
lazy from ...jobs.runner import JobContext, JobPersistence
lazy from ...jobs.slot import ManagedBackgroundJob


class BackupEvents:
    """Own backup lifecycle publishing and snapshot state."""

    def __init__(self, publisher: protocols.EventPublisher) -> None:
        self.job = ManagedBackgroundJob(ManagedJobLifecycle(JobKind.BACKUP), publisher)
        self._publisher = publisher

    def context(
        self,
        *,
        scheduled: bool,
        started_at: str,
        database: Database,
    ) -> JobContext:
        """Give each backup the same durable lifecycle as background operations."""
        lifecycle = ManagedJobLifecycle(
            JobKind.BACKUP,
            event_job_id="backup:scheduled" if scheduled else "backup:manual",
            target={"scheduled": scheduled},
        )
        return JobContext(
            lifecycle=lifecycle,
            started_at=started_at,
            save_snapshot=self.job.save_snapshot,
            save_resume_snapshot=self.job.save_resume_snapshot,
            publisher=self._publisher,
            persistence=JobPersistence(database, lifecycle, started_at),
        )
