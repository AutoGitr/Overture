"""A run's progress log: numbered as published, persisted in batches, paged."""

lazy from typing import Any

lazy import pytest
lazy from sqlmodel import col, select

lazy from overture.db.models.job_result import JobLogLine, JobRun
lazy from overture.db.session import CHUNK_SIZE, Database
lazy from overture.jobs import runner
lazy from overture.jobs.kinds import INTERRUPTED_MESSAGE, JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import BulkAssetTally
lazy from overture.services import job_results
lazy from overture.utils.errors import PublicServiceError
lazy from tests.runtime_helpers import JobProbe


async def _run(probe: JobProbe, database: Database, lines: int) -> None:
    async with run_managed_job(
        probe.context, BulkAssetTally(), database=database
    ) as job:
        await job.started()
        await job.planned(lines)
        for index in range(lines):
            await job.report(
                JobOutcome.QUEUED, f"Movie {index} (poster)", "OvertureDB artwork"
            )


async def test_each_event_numbers_the_line_it_adds_and_the_log_is_paged(
    database: Database,
) -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))

    await _run(probe, database, 3)

    events = probe.publisher.payloads("match.progress")
    run_id = events[0]["run_id"]
    assert [(e["run_id"], e["log_total"], "log" in e) for e in events] == [
        (run_id, 0, False),
        (run_id, 1, True),
        (run_id, 2, True),
        (run_id, 3, True),
    ]
    assert [e["log_outcomes"] for e in events] == [
        {},
        {"Queued": 1},
        {"Queued": 2},
        {"Queued": 3},
    ]
    _, terminal = probe.terminal()
    assert (terminal["run_id"], terminal["log_total"]) == (run_id, 3)

    page = await job_results.log_page(database, run_id, 1, 10)
    assert (page.total, page.offset) == (3, 1)
    assert [entry.target for entry in page.items] == [
        "Movie 1 (poster)",
        "Movie 2 (poster)",
    ]


async def test_a_failed_run_ends_its_persisted_log_on_the_error(
    database: Database,
) -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.SYNC))

    async with run_managed_job(probe.context, BulkAssetTally(), database=database):
        raise OSError("disk gone")

    _, terminal = probe.terminal()
    page = await job_results.log_page(database, terminal["run_id"], 0, 10)
    assert [entry.format() for entry in page.items] == [
        "Error Library sync - disk gone"
    ]
    assert terminal["log_total"] == 1


async def test_log_lines_are_written_in_batches(
    monkeypatch: pytest.MonkeyPatch, database: Database
) -> None:
    written: list[int] = []
    persist = job_results.persist

    async def counting(*args: Any, **kwargs: Any) -> None:
        written.append(len(kwargs["log"]))
        await persist(*args, **kwargs)

    monkeypatch.setattr(runner.job_results, "persist", counting)
    # Only full batches and the terminal event write, however long the run takes.
    monkeypatch.setattr(runner, "_PROGRESS_SUMMARY_INTERVAL", float("inf"))
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))

    await _run(probe, database, CHUNK_SIZE + 10)

    # Started, then one write per full batch, then the rest with the terminal event.
    assert written == [0, CHUNK_SIZE, 10]
    _, terminal = probe.terminal()
    page = await job_results.log_page(database, terminal["run_id"], CHUNK_SIZE, 50)
    assert page.total == CHUNK_SIZE + 10
    assert len(page.items) == 10


async def test_a_new_run_replaces_the_earlier_runs_of_its_kind(
    database: Database,
) -> None:
    async def persist(run_id: str, kind: JobKind) -> None:
        await job_results.persist(
            database,
            run_id=run_id,
            kind=kind,
            started_at="2026-01-01T00:00:00+00:00",
            event=f"{kind.event_prefix}.started",
            summary={},
            results=[{"row": 1}],
            log=[{"outcome": "Started", "target": "Run", "reason": "x", "at": "now"}],
        )

    await persist("old", JobKind.SYNC)
    await persist("other", JobKind.BULK_ART)
    await persist("new", JobKind.SYNC)

    async with database.read_session() as session:
        runs = (await session.exec(select(JobRun.id).order_by(col(JobRun.id)))).all()
        lines = (await session.exec(select(JobLogLine.run_id))).all()
    assert runs == ["new", "other"]
    assert sorted(lines) == ["new", "other"]


async def test_an_interrupted_run_ends_its_log_on_the_interruption(
    database: Database,
) -> None:
    await job_results.persist(
        database,
        run_id="run-1",
        kind=JobKind.SYNC,
        started_at="2026-01-01T00:00:00+00:00",
        event="sync.progress",
        summary={"log_total": 1, "log_outcomes": {"Added": 1}},
        results=[],
        log=[{"outcome": "Added", "target": "Alien", "reason": "new", "at": "now"}],
    )

    await job_results.interrupt_unfinished(database)

    page = await job_results.log_page(database, "run-1", 0, 10)
    assert [entry.reason for entry in page.items] == ["new", INTERRUPTED_MESSAGE]
    [run] = (await job_results.latest_runs(database)).values()
    assert run.summary["log_total"] == 2
    assert run.summary["log_outcomes"] == {"Added": 1, "Skipped": 1}


async def test_a_cleared_run_has_no_log_to_page(database: Database) -> None:
    await job_results.persist(
        database,
        run_id="run-1",
        kind=JobKind.SYNC,
        started_at="2026-01-01T00:00:00+00:00",
        event="sync.completed",
        summary={},
        results=[],
        log=[],
    )
    async with database.write_session() as session:
        run = await session.get(JobRun, "run-1")
        assert run is not None
        run.cleared = True
        session.add(run)

    with pytest.raises(PublicServiceError) as raised:
        await job_results.log_page(database, "run-1", 0, 10)
    assert raised.value.status_code == 404


async def test_a_log_pages_by_outcome(
    database: Database,
) -> None:
    outcomes = ["Added", "Error", "Unchanged", "Added", "Error", "Added"]
    await job_results.persist(
        database,
        run_id="run-1",
        kind=JobKind.SYNC,
        started_at="2026-01-01T00:00:00+00:00",
        event="sync.completed",
        summary={},
        results=[],
        log=[
            {"outcome": outcome, "target": f"Movie {index}", "reason": "", "at": "now"}
            for index, outcome in enumerate(outcomes)
        ],
    )

    page = await job_results.log_page(
        database,
        "run-1",
        1,
        2,
        frozenset({JobOutcome.ADDED, JobOutcome.ERROR}),
    )

    assert (page.total, page.offset) == (5, 1)
    assert [entry.target for entry in page.items] == ["Movie 1", "Movie 3"]
    unfiltered = await job_results.log_page(database, "run-1", 4, 10)
    assert (unfiltered.total, [entry.target for entry in unfiltered.items]) == (
        6,
        ["Movie 4", "Movie 5"],
    )
