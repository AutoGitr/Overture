"""Publishing and logging the lifecycle events of jobs."""

lazy import logging
lazy from collections.abc import Callable, Mapping
lazy from dataclasses import dataclass
lazy from typing import Any

lazy from .. import protocols
lazy from ..utils.job_events import build_job_payload
lazy from ..utils.time import format_duration, parse_utc_datetime
lazy from .kinds import JobKind, LifecycleStatus
lazy from .progress_log import JobLogEntry

logger = logging.getLogger(__name__)

#: Statuses that end a run.
_TERMINAL_STATUSES = frozenset(status for status in LifecycleStatus if status.terminal)

#: Integer payload fields a run's end line does not list as counters: the
#: progress it reports first, and the sizes of its persisted log and results.
_NOT_SUMMARISED = frozenset({"done", "total", "log_total", "results_total"})


@dataclass(slots=True, frozen=True)
class ManagedJobLifecycle:
    """What a managed job slot's events say about the job they come from."""

    kind: JobKind
    event_job_id: str | None = None
    target: Mapping[str, Any] | None = None


def label(name: str) -> str:
    """Return a run's name as the start of a sentence (``Library sync``)."""
    return f"{name[:1].upper()}{name[1:]}"


def _run_ending(status: str, payload: Mapping[str, Any]) -> str:
    """Say how a run ended, how long it took, why it failed and what it counted."""
    text = status
    started = parse_utc_datetime(payload.get("started_at"))
    finished = parse_utc_datetime(payload.get("finished_at"))
    if started is not None and finished is not None:
        duration = format_duration((finished - started).total_seconds())
        text += f" {'in' if status == 'completed' else 'after'} {duration}"
    job: Mapping[str, Any] = payload.get("job") or {}
    if error := job.get("error"):
        text += f": {error['message']}"
    counts: list[str] = []
    if type(done := payload.get("done")) is int:
        total = payload.get("total")
        counts.append(f"{done}/{total} done" if type(total) is int else f"{done} done")
    counts += [
        f"{key.replace('_', ' ')} {value}"
        for key, value in payload.items()
        if type(value) is int and value and key not in _NOT_SUMMARISED
    ]
    return f"{text} - {', '.join(counts)}" if counts else text


def log_job_event(
    name: str,
    status: str,
    payload: Mapping[str, Any],
    *,
    exc: BaseException | None = None,
) -> None:
    """Write one lifecycle event of the run *name* to the container log.

    The run's start and end are one line each; the end line sums the run up.
    A progress entry is one line at its outcome's level, so the container log
    and the web UI tell the same story. A failed event's entry repeats the
    error its end line carries, so it is not written twice.
    """
    run = label(name)
    if status == "started":
        logger.info("%s started", run)
    if (raw := payload.get("log")) is not None and status != "failed":
        entry = JobLogEntry.model_validate(raw)
        logger.log(entry.outcome.log_level, "%s: %s", run, entry.format())
    if status in _TERMINAL_STATUSES:
        logger.log(
            logging.ERROR if status == "failed" else logging.INFO,
            "%s %s",
            run,
            _run_ending(status, payload),
            exc_info=exc,
        )


async def publish_job_lifecycle(
    kind: JobKind,
    status: str,
    *,
    publisher: protocols.EventPublisher,
    event_job_id: str | None = None,
    target: Mapping[str, Any] | None = None,
    name: str | None = None,
    exc: BaseException | None = None,
    save_snapshot: Callable[[str, dict[str, Any]], None] | None = None,
    save_resume_snapshot: Callable[[str, dict[str, Any]], None] | None = None,
    before_publish: Callable[[str, Any], None] | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """Publish a standard job lifecycle event with a stable job envelope.

    *name* names a run (``library sync``): the event is written to the
    container log, with *exc* as the failure's traceback. Per-item lifecycles
    (downloads) pass no name and log their own outcome.
    """
    event_payload = build_job_payload(
        kind,
        status,
        event_job_id=event_job_id,
        target=target,
        **payload,
    )
    resume_payload = (
        build_job_payload(
            kind,
            "progress",
            event_job_id=event_job_id,
            target=target,
            **payload,
        )
        if save_resume_snapshot is not None and LifecycleStatus(status).running
        else None
    )

    projected = False

    def update_projection(
        published_event: str, published_payload: dict[str, Any]
    ) -> None:
        nonlocal projected
        if projected:
            return
        projected = True
        if save_snapshot is not None:
            save_snapshot(published_event, published_payload)
        if save_resume_snapshot is not None and resume_payload is not None:
            save_resume_snapshot(
                f"{kind.event_prefix}.{LifecycleStatus.PROGRESS}", resume_payload
            )
        if before_publish is not None:
            before_publish(published_event, published_payload)

    try:
        await publisher.broadcast(
            f"{kind.event_prefix}.{status}",
            event_payload,
            before_publish=update_projection,
        )
    except Exception:
        logger.exception("Could not deliver the %s %s event", kind, status)
        update_projection(f"{kind.event_prefix}.{status}", event_payload)
    if name is not None:
        log_job_event(name, status, event_payload, exc=exc)
    return event_payload
