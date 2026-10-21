"""JobTally and run_managed_job: the shared background-job lifecycle.

Five runners depend on this primitive to decide stopped/completed/failed and
to shape their payloads, so its contract is tested directly rather than only
through each runner.
"""

lazy import logging
lazy from typing import Any

lazy import pytest
lazy from _pytest.logging import LogCaptureFixture
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from overture.db.session import Database
lazy from overture.jobs import runner
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle, publish_job_lifecycle
lazy from overture.jobs.progress_log import JobLogEntry, JobOutcome, log_entry
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import AssetScanTally, BulkAssetTally, ServerAuditTally
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import JobProbe


def _tally() -> BulkAssetTally:
    return BulkAssetTally()


async def test_a_named_run_logs_its_start_its_entries_and_one_summary(
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="overture.jobs")
    started_at = "2026-01-01T00:00:00+00:00"

    async def publish(status: str, **payload: Any) -> dict[str, Any]:
        return await publish_job_lifecycle(
            JobKind.BULK_ART,
            status,
            name="bulk art match",
            publisher=NullEventPublisher(),
            **payload,
        )

    await publish(
        "started",
        started_at=started_at,
        log=log_entry(JobOutcome.STARTED, "Matching", "planning 3 slots"),
    )
    await publish(
        "progress",
        done=1,
        total=3,
        log=log_entry(JobOutcome.QUEUED, "Movie (poster)", "OvertureDB artwork"),
    )
    await publish(
        "progress",
        done=2,
        total=3,
        log=log_entry(JobOutcome.ERROR, "Show (poster)", "lookup failed"),
    )
    await publish(
        "completed",
        started_at=started_at,
        finished_at="2026-01-01T00:01:12+00:00",
        done=3,
        total=3,
        queued=1,
        skipped=0,
        errors=1,
        results=[{"large": "payload"}],
        results_total=1,
    )

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.INFO, "Bulk art match started"),
        (logging.DEBUG, "Bulk art match: Started Matching - planning 3 slots"),
        (logging.DEBUG, "Bulk art match: Queued Movie (poster) - OvertureDB artwork"),
        (logging.WARNING, "Bulk art match: Error Show (poster) - lookup failed"),
        (
            logging.INFO,
            "Bulk art match completed in 1m 12s - 3/3 done, queued 1, errors 1",
        ),
    ]


async def test_a_failed_run_is_one_error_line(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="overture.jobs")
    failure = OSError("disk gone")

    await publish_job_lifecycle(
        JobKind.SYNC,
        "failed",
        publisher=NullEventPublisher(),
        name="library sync",
        exc=failure,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:03+00:00",
        done=4,
        total=10,
        errors=1,
        error="Disk gone",
    )

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert record.getMessage() == (
        "Library sync failed after 3.0s: Disk gone - 4/10 done, errors 1"
    )
    assert record.exc_info is not None
    assert record.exc_info[1] is failure


async def test_an_unnamed_lifecycle_logs_nothing(caplog: LogCaptureFixture) -> None:
    """Per-item lifecycles, such as downloads, log their own outcome."""
    caplog.set_level(logging.DEBUG, logger="overture.jobs")

    for status in ("started", "completed", "failed"):
        await publish_job_lifecycle(
            JobKind.DOWNLOAD, status, publisher=NullEventPublisher(), error="x"
        )

    assert caplog.records == []


def test_every_outcome_has_a_container_log_level() -> None:
    assert {outcome: outcome.log_level for outcome in JobOutcome} == {
        JobOutcome.STARTED: logging.DEBUG,
        JobOutcome.ADDED: logging.INFO,
        JobOutcome.UPDATED: logging.INFO,
        JobOutcome.UNCHANGED: logging.DEBUG,
        JobOutcome.REMOVED: logging.INFO,
        JobOutcome.QUEUED: logging.DEBUG,
        JobOutcome.DOWNLOADED: logging.DEBUG,
        JobOutcome.ADOPTED: logging.DEBUG,
        JobOutcome.MATCHED: logging.DEBUG,
        JobOutcome.MISMATCH: logging.INFO,
        JobOutcome.CHECKED: logging.DEBUG,
        JobOutcome.NO_MATCH: logging.DEBUG,
        JobOutcome.SKIPPED: logging.DEBUG,
        JobOutcome.ERROR: logging.WARNING,
    }


# --- JobTally ----------------------------------------------------------------


def test_counters_start_at_zero_and_accumulate() -> None:
    tally = _tally()

    assert tally.done == 0
    tally.done += 1
    tally.queued += 3

    assert tally.done == 1
    assert tally.queued == 3


def test_every_tally_reports_the_shared_lifecycle_counters() -> None:
    """done/total/errors are what run_managed_job and the clients rely on."""
    for tally in (BulkAssetTally(), AssetScanTally(), ServerAuditTally()):
        assert {"done", "total", "errors"} <= set(tally.counters())


def test_as_payload_returns_every_declared_counter() -> None:
    tally = _tally()
    tally.done = 2

    assert tally.as_payload() == {
        "done": 2,
        "total": None,
        "errors": 0,
        "queued": 0,
        "downloaded": 0,
        "adopted": 0,
        "skipped": 0,
        "no_match": 0,
        "settled": 0,
    }


def test_as_payload_merges_extras_over_counters() -> None:
    """Runners layer per-event fields (a log line, a batch) onto the counters."""
    tally = _tally()

    payload = tally.as_payload(log="hello", done=99)

    assert payload["log"] == "hello"
    assert payload["done"] == 99


def test_collect_returns_only_the_newly_added_items() -> None:
    """Progress events carry each result once, not the whole list every time."""
    tally = ServerAuditTally()

    assert tally.collect("a") == ["a"]
    assert tally.collect("b", "c") == ["b", "c"]
    assert tally.collected == ["a", "b", "c"]


def test_collect_with_no_items_returns_an_empty_batch() -> None:
    tally = AssetScanTally()

    assert tally.collect() == []
    assert tally.as_payload()["issues_found"] == 0


def test_count_key_is_published_on_every_event_but_the_list_is_not() -> None:
    tally = ServerAuditTally()
    tally.collect("a", "b")

    progress = tally.as_payload()
    terminal = tally.as_payload(include_collected=True)

    assert progress["results_found"] == 2
    assert "results" not in progress
    assert terminal["results"] == ["a", "b"]


def test_a_tally_without_a_collect_key_never_publishes_a_list() -> None:
    tally = _tally()

    assert tally.as_payload(include_collected=True) == tally.as_payload()


# --- run_managed_job ---------------------------------------------------------


async def test_completed_is_published_once_with_counters_and_timestamp() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    tally = _tally()

    async with run_managed_job(probe.context, tally) as job:
        await job.started()
        await job.planned(2)
        tally.done = 2
        tally.queued = 1
        await job.progress(log=log_entry(JobOutcome.QUEUED, "A", "queued"))

    assert probe.names() == [
        "match.started",
        "match.progress",
        "match.progress",
        "match.completed",
    ]
    assert "total" not in probe.publisher.payloads("match.started")[0]
    assert probe.publisher.payloads("match.progress")[0]["total"] == 2
    event, payload = probe.terminal()
    assert event == "match.completed"
    assert payload["done"] == 2
    assert payload["queued"] == 1
    assert payload["finished_at"]
    assert payload["job"] == {"kind": "bulk_art", "status": "completed"}


async def test_report_counts_exactly_the_lines_it_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each counter equals the lines starting with its outcome word."""
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    tally = _tally()

    with caplog.at_level(logging.DEBUG, logger="overture.jobs"):
        async with run_managed_job(probe.context, tally) as job:
            await job.started(total=0)
            await job.report(JobOutcome.QUEUED, "A (poster)", "OvertureDB artwork")
            await job.report(JobOutcome.SKIPPED, "3 art slots", "saved", count=3)
            await job.report(
                JobOutcome.DOWNLOADED, "A (poster)", "written to disk", finished=False
            )
            await job.report(JobOutcome.ERROR, "B (poster)", "lookup failed")

    lines = [
        JobLogEntry.model_validate(payload["log"]).format()
        for name, payload in probe.events
        if name == "match.progress" and payload.get("log")
    ]
    assert lines == [
        "Queued A (poster) - OvertureDB artwork",
        "Skipped 3 art slots - saved",
        "Downloaded A (poster) - written to disk",
        "Error B (poster) - lookup failed",
    ]
    assert (tally.queued, tally.skipped, tally.downloaded, tally.errors) == (1, 3, 1, 1)
    assert tally.done == 5
    # The container log carries the same lines, word for word.
    logged = [record.getMessage() for record in caplog.records]
    assert [line for line in logged if line.startswith("Bulk art match: ")] == [
        f"Bulk art match: {line}" for line in lines
    ]
    assert [
        record.levelno for record in caplog.records if "Error B" in record.getMessage()
    ] == [logging.WARNING]


async def test_stopped_is_published_when_cancellation_was_requested() -> None:
    probe = JobProbe(
        lifecycle=ManagedJobLifecycle(JobKind.BULK_ART), stop_requested=True
    )
    tally = _tally()

    async with run_managed_job(probe.context, tally) as job:
        assert job.stop_requested() is True

    _, payload = probe.terminal()
    assert payload["job"]["status"] == "stopped"


async def test_failure_publishes_failed_counts_the_error_and_is_swallowed() -> None:
    """A caught failure ends the job cleanly; the body's error does not escape."""
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    tally = _tally()

    async with run_managed_job(probe.context, tally):
        raise ValueError("work blew up")

    _, payload = probe.terminal()
    assert payload["job"]["status"] == "failed"
    assert payload["errors"] == 1
    assert payload["job"]["error"]["message"] == "work blew up"
    assert (
        JobLogEntry.model_validate(payload["log"]).format()
        == "Error Bulk art match - work blew up"
    )


async def test_failure_adds_to_an_error_count_the_body_already_raised() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    tally = _tally()

    async with run_managed_job(probe.context, tally):
        tally.errors = 3
        raise OSError("disk gone")

    _, payload = probe.terminal()
    assert payload["errors"] == 4


async def test_unexpected_exception_fails_the_owned_job() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    async with run_managed_job(probe.context, _tally()):
        raise KeyError("bug")
    assert probe.terminal()[1]["job"]["status"] == "failed"


async def test_the_catch_list_can_be_widened_per_runner() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.SYNC))

    async with run_managed_job(
        probe.context,
        _tally(),
        catch=(KeyError,),
    ):
        raise KeyError("handled here")

    _, payload = probe.terminal()
    assert payload["job"]["status"] == "failed"


async def test_default_catch_covers_the_database_error_runners_expect() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))

    async with run_managed_job(probe.context, _tally()):
        raise SQLAlchemyError("rollback")

    assert probe.terminal()[1]["job"]["status"] == "failed"


async def test_a_run_plans_its_total_once() -> None:
    """The total is unknown while planning, then fixed for the rest of the run."""
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))

    async with run_managed_job(probe.context, _tally()) as job:
        await job.started()
        await job.planned(3)
        with pytest.raises(RuntimeError, match="planned once"):
            await job.planned(4)

    started, planned = (
        probe.publisher.payloads("match.started")[0],
        probe.publisher.payloads("match.progress")[0],
    )
    assert "total" not in started
    assert planned["total"] == probe.terminal()[1]["total"] == 3


async def test_terminal_extras_are_added_to_the_final_event_only() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.ASSET_SCAN))
    tally = AssetScanTally()

    async with run_managed_job(
        probe.context,
        tally,
        terminal_extras=lambda t: {"total_folders": t.total},
    ) as job:
        tally.total = 5
        await job.progress(log=log_entry(JobOutcome.CHECKED, "Folder", "scanning"))

    progress = probe.publisher.payloads("assets.scan.progress")[0]
    assert "total_folders" not in progress

    _, terminal = probe.terminal()
    assert terminal["total_folders"] == 5


async def test_collected_results_reach_the_terminal_event_in_full() -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.SERVER_AUDIT))
    tally = ServerAuditTally()

    async with run_managed_job(
        probe.context,
        tally,
    ) as job:
        await job.progress(results=tally.collect({"id": 1}))
        await job.progress(results=tally.collect({"id": 2}))

    first, second = probe.publisher.payloads("server.audit.progress")
    assert first["results"] == [{"id": 1}]
    assert second["results"] == [{"id": 2}]

    _, terminal = probe.terminal()
    assert terminal["results"] == [{"id": 1}, {"id": 2}]
    assert terminal["results_found"] == 2


async def test_a_stopped_run_ends_on_the_stopped_status() -> None:
    """The slot owns the one cancellation flag every runner reads."""
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.SYNC), stop_requested=True)

    async with run_managed_job(probe.context, _tally()) as job:
        assert job.stop_requested() is True

    assert probe.terminal()[1]["job"]["status"] == "stopped"


async def test_running_events_are_saved_as_resume_snapshots() -> None:
    """A reconnecting client restores the latest progress, not the terminal one."""
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    tally = _tally()

    async with run_managed_job(probe.context, tally) as job:
        await job.started(total=1)
        await job.progress(log=log_entry(JobOutcome.QUEUED, "A", "working"))

    assert [event for event, _ in probe.resume_snapshots] == [
        "match.progress",
        "match.progress",
    ]
    # Terminal events are saved as the final snapshot instead.
    assert probe.terminal()[0] == "match.completed"


async def test_started_publishes_only_what_the_runner_passes() -> None:
    """The started event must not gain a wall of zero counters."""
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))

    async with run_managed_job(probe.context, _tally()) as job:
        await job.started(total=7)

    payload = probe.publisher.payloads("match.started")[0]
    assert payload["total"] == 7
    assert "queued" not in payload


async def test_progress_without_new_results_is_persisted_at_most_once_a_second(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
) -> None:
    persisted: list[tuple[str, int]] = []
    clock = [100.0]

    async def persist(_database: Database, **kwargs: Any) -> None:
        persisted.append((kwargs["event"].rsplit(".", 1)[1], len(kwargs["results"])))

    monkeypatch.setattr(runner.job_results, "persist", persist)
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    tally = AssetScanTally()

    async with run_managed_job(JobProbe().context, tally, database=database) as job:
        await job.started()
        for _ in range(50):
            await job.progress(issues=[])
        await job.progress(issues=tally.collect({"current_path": "/a.jpg"}))
        await job.progress(issues=[])
        clock[0] += 1.0
        await job.progress(issues=[])

    assert persisted == [
        ("started", 0),
        ("progress", 1),
        ("progress", 0),
        ("completed", 0),
    ]
