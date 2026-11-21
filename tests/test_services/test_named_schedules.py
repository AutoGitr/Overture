"""How a scheduled run's jobs are summarised for its schedule."""

lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.schemas.schedules import ScheduleRunSummary
lazy from overture.services.named_schedules import job_run_summary


def test_job_run_summary_adds_up_jobs_and_spans_their_run() -> None:
    art = {
        "started_at": "2026-10-27T03:00:00+00:00",
        "finished_at": "2026-10-27T03:00:30+00:00",
        "log_targets": {"Queued": 3, "Error": 1},
    }
    themes = {
        "started_at": "2026-10-27T03:00:05+00:00",
        "finished_at": "2026-10-27T03:01:00+00:00",
        "log_targets": {"Queued": 2},
    }

    summary = job_run_summary(
        [art, None, themes],
        {
            JobOutcome.QUEUED: "queued",
            JobOutcome.SKIPPED: "skipped",
            JobOutcome.ERROR: "errors",
        },
        failed=True,
    )

    assert summary == ScheduleRunSummary(
        duration_seconds=60.0, counts={"queued": 5, "errors": 1}, failed=True
    )


def test_job_run_summary_of_jobs_that_never_ran_is_empty() -> None:
    assert (
        job_run_summary([None], {JobOutcome.QUEUED: "queued"}) == ScheduleRunSummary()
    )
