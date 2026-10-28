"""Shared public schema primitives."""

lazy from enum import StrEnum
lazy from typing import Annotated, Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..jobs.kinds import JobKind, LifecycleStatus
lazy from ..jobs.progress_log import JobLogEntry, JobOutcome
lazy from ..utils.types import JsonValue
lazy from .base import StrictBaseModel
lazy from .validators import UniqueList


class MediaFolderScope(StrictBaseModel):
    """Media folders a folder-based job visits: chosen roots or chosen items."""

    movie_folders: list[str] = Field(default_factory=list[str])
    show_folders: list[str] = Field(default_factory=list[str])
    item_ids: UniqueList[Annotated[int, Field(gt=0)]] | None = Field(
        default=None,
        description="Visit these items' folders instead of the selected roots.",
    )

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Explicit items replace roots; an empty list never means all items."""
        if self.item_ids is not None:
            if self.movie_folders or self.show_folders:
                raise ValueError("Select either folders or item_ids")
            if not self.item_ids:
                raise ValueError("item_ids must include at least one item")
        return self


class Status(StrEnum):
    """What a command did."""

    OK = "ok"
    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    STOPPING = "stopping"
    NOT_RUNNING = "not_running"
    IDLE = "idle"
    QUEUED = "queued"
    ENQUEUED = "enqueued"
    CLEARED = "cleared"
    DELETED = "deleted"
    DISABLED = "disabled"
    NO_JOBS_SELECTED = "no_jobs_selected"


class StatusResponse(StrictBaseModel):
    """What a command did."""

    status: Status

    @classmethod
    def start(cls, started: bool) -> Self:
        """Say whether a job started, or was already running."""
        return cls(status=Status.STARTED if started else Status.ALREADY_RUNNING)

    @classmethod
    def stop(cls, stopping: bool) -> Self:
        """Say whether a running job was asked to stop, or none was running."""
        return cls(status=Status.STOPPING if stopping else Status.NOT_RUNNING)


class EnqueuedJobResponse(StrictBaseModel):
    """A download job that was queued."""

    job_id: str
    status: Literal[Status.ENQUEUED] = Status.ENQUEUED


class MonitorUpdate(StrictBaseModel):
    """Whether an item or collection is monitored."""

    monitored: bool


class SaveSelectionResponse(StrictBaseModel):
    """A recorded selection and the download job that fetches it.

    An item without a local folder downloads nothing, so its selection is
    only recorded (``selected``) and carries no job.
    """

    job_id: str | None
    status: Literal["enqueued", "existing", "selected"]

    @classmethod
    def of(cls, job_id: str | None, *, created: bool) -> Self:
        """Describe a recorded selection by its download job, if any."""
        if job_id is None:
            return cls(job_id=None, status="selected")
        return cls(job_id=job_id, status="enqueued" if created else "existing")


class MonitoredResponse(StrictBaseModel):
    """Monitored flag response."""

    monitored: bool


class BulkMonitorResponse(StrictBaseModel):
    """How many records a bulk monitor update changed."""

    updated: int


class PublicError(StrictBaseModel):
    """Stable public error object."""

    message: str


class JobMetadata(StrictBaseModel):
    """Stable job envelope metadata shared by WebSocket job payloads."""

    kind: JobKind
    status: LifecycleStatus
    id: str | None = None
    target: dict[str, JsonValue] | None = None
    error: PublicError | None = None


class JobEnvelope(StrictBaseModel):
    """Optional top-level job envelope for long-running work events."""

    job: JobMetadata | None = None
    log: JobLogEntry | None = Field(
        default=None, description="The entry this event adds to the job's log."
    )
    run_id: str | None = Field(
        default=None,
        description="The persisted run whose log and findings the job pages.",
    )
    schedule: str | None = Field(
        default=None,
        description="The saved schedule that started the run; none if started by hand.",
    )
    log_total: int | None = Field(
        default=None,
        description="Lines in the run's log, including the one this event adds.",
    )
    log_outcomes: dict[JobOutcome, int] | None = Field(
        default=None,
        description="The run's log lines per outcome, with the one this event adds.",
    )
