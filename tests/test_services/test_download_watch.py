"""The download watch, and what a bulk run reports while it drains."""

lazy import asyncio
lazy from typing import Any, cast, override

lazy import pytest

lazy from overture.jobs.progress_log import JobLogEntry
lazy from overture.jobs.runner import JobContext, ManagedJob
lazy from overture.jobs.tally import BulkAssetTally
lazy from overture.services.bulk_common import (
    SelectionChangedError,
    queue_and_report,
    report_downloads,
)
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.downloads.watch import DownloadOutcome, DownloadWatch


class _Context:
    """The slice of a job context that publishing a progress event uses."""

    def __init__(self, *, stop_after: int | None = None) -> None:
        self.logs: list[str] = []
        self.stop_after = stop_after
        self.stop_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.persistence = None

    def stop_requested(self) -> bool:
        if self.stop_after is not None and len(self.logs) >= self.stop_after:
            self.stop_event.set()
            return True
        return self.stop_event.is_set()

    async def publish_lifecycle(
        self,
        _status: str,
        **payload: Any,
    ) -> None:
        if "log" in payload:
            self.logs.append(JobLogEntry.model_validate(payload["log"]).format())


class _Downloads:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def cancel_watch(self, watch: DownloadWatch) -> None:
        for job_id in watch.active_job_ids:
            watch.settle(job_id, "the download was cancelled")
        self.cancelled.set()


def _job(context: _Context) -> ManagedJob[BulkAssetTally]:
    return ManagedJob(
        cast("JobContext", context),
        BulkAssetTally(),
    )


@pytest.mark.parametrize("queue_state", ["new", "existing", "changed", "failed"])
async def test_queue_outcome_is_one_counted_line(queue_state: str) -> None:
    context = _Context()
    job = _job(context)

    async def queue() -> bool:
        if queue_state == "failed":
            raise OSError("disk unavailable")
        if queue_state == "changed":
            raise SelectionChangedError
        return queue_state == "new"

    succeeded = await queue_and_report(job, "Movie", "OvertureDB theme", queue)

    assert succeeded is (queue_state in {"new", "existing"})
    assert job.tally.queued == int(queue_state == "new")
    assert job.tally.skipped == int(queue_state in {"existing", "changed"})
    assert job.tally.errors == int(queue_state == "failed")
    assert job.tally.done == 1
    assert context.logs == [
        {
            "new": "Queued Movie - OvertureDB theme",
            "existing": (
                "Skipped Movie - OvertureDB theme; an identical download is "
                "already queued or running"
            ),
            "changed": (
                "Skipped Movie - OvertureDB theme; not queued: the selection "
                "changed during the run"
            ),
            "failed": (
                "Error Movie - could not queue the download (OvertureDB theme): "
                "disk unavailable"
            ),
        }[queue_state]
    ]


async def test_watch_reports_the_jobs_it_queued_and_ignores_the_rest() -> None:
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")
    watch.tracking("Firefly")("job-2")

    watch.settle("job-1", None)
    watch.settle("job-2", "disk full")
    watch.settle("job-someone-else", None)

    watch.close()
    assert [outcome async for outcome in watch.stream()] == [
        DownloadOutcome("Alien (poster)", None),
        DownloadOutcome("Firefly", "disk full"),
    ]


async def test_watch_waits_for_a_job_that_has_not_settled_yet() -> None:
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")

    async def settle_later() -> None:
        await asyncio.sleep(0)
        watch.settle("job-1", None)

    settling = asyncio.create_task(settle_later())
    watch.close()
    outcomes = [outcome async for outcome in watch.stream()]
    await settling

    assert outcomes == [DownloadOutcome("Alien (poster)", None)]


async def test_report_downloads_counts_what_landed_and_what_failed() -> None:
    context = _Context()
    job = _job(context)
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")
    watch.tracking("Firefly")("job-2")
    watch.tracking("Heat (poster)")("job-3")
    watch.tracking("Ran (poster)")("job-4")
    watch.settle("job-1", None)
    watch.settle("job-2", "disk full")
    watch.settle("job-3", None, unchanged=True)
    watch.settle("job-4", "the download was cancelled", cancelled=True)

    async with report_downloads(
        job, watch, downloads=cast("DownloadService", _Downloads())
    ):
        pass

    assert job.tally.downloaded == 1
    assert job.tally.adopted == 1
    assert job.tally.skipped == 1
    assert job.tally.errors == 1
    assert job.tally.settled == 4
    # A download's outcome follows the target's decision; it is not a new target.
    assert job.tally.done == 0
    assert context.logs == [
        "Downloaded Alien (poster) - written to disk",
        "Error Firefly - download failed: disk full",
        (
            "Adopted Heat (poster) - download is identical to the local file; "
            "selection saved, nothing written"
        ),
        "Skipped Ran (poster) - download cancelled before it finished",
    ]


async def test_report_downloads_gives_up_the_wait_when_the_run_is_stopped() -> None:
    context = _Context(stop_after=1)
    job = _job(context)
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")
    watch.tracking("Firefly")("job-2")
    watch.settle("job-1", None)

    async with report_downloads(
        job, watch, downloads=cast("DownloadService", _Downloads())
    ):
        pass

    assert job.tally.downloaded == 1
    assert context.logs == ["Downloaded Alien (poster) - written to disk"]


async def test_report_downloads_publishes_before_matching_finishes() -> None:
    context = _Context()
    job = _job(context)
    watch = DownloadWatch()

    async with report_downloads(
        job, watch, downloads=cast("DownloadService", _Downloads())
    ):
        watch.tracking("Alien (poster)")("job-1")
        watch.settle("job-1", None)
        await asyncio.sleep(0)

        assert context.logs == ["Downloaded Alien (poster) - written to disk"]


async def test_report_downloads_cancels_watch_when_stopped() -> None:
    context = _Context()
    job = _job(context)
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")
    watch.tracking("Firefly (theme)")("job-2")

    downloads = _Downloads()
    async with report_downloads(
        job, watch, downloads=cast("DownloadService", downloads)
    ):
        context.stop_event.set()
        await downloads.cancelled.wait()

    assert watch.active_job_ids == []


async def test_stop_cancels_downloads_after_matching_finishes() -> None:
    context = _Context()
    job = _job(context)
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")
    matching_finished = asyncio.Event()
    downloads = _Downloads()

    async def run() -> None:
        async with report_downloads(
            job, watch, downloads=cast("DownloadService", downloads)
        ):
            matching_finished.set()

    async with asyncio.timeout(2):
        task = asyncio.create_task(run())
        await matching_finished.wait()
        context.stop_event.set()
        await task

    assert downloads.cancelled.is_set()
    assert watch.active_job_ids == []


async def test_stop_cancels_jobs_queued_while_matching_winds_down() -> None:
    context = _Context()
    job = _job(context)
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")
    downloads = _Downloads()

    async with asyncio.timeout(2):
        async with report_downloads(
            job, watch, downloads=cast("DownloadService", downloads)
        ):
            context.stop_event.set()
            await downloads.cancelled.wait()
            watch.tracking("Firefly (theme)")("job-2")

    assert watch.active_job_ids == []


async def test_cancellation_failure_does_not_leave_reporter_waiting() -> None:
    context = _Context()
    watch = DownloadWatch()
    watch.tracking("Alien (poster)")("job-1")

    class FailingDownloads(_Downloads):
        @override
        async def cancel_watch(
            self, watch: DownloadWatch, *, interrupted: bool = False
        ) -> None:
            raise OSError("database unavailable")

    async with asyncio.timeout(2):
        with pytest.raises(OSError, match="database unavailable"):
            async with report_downloads(
                _job(context),
                watch,
                downloads=cast("DownloadService", FailingDownloads()),
            ):
                context.stop_event.set()
