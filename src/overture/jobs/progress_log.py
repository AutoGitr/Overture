"""One shape for every entry a job writes to its progress log.

Each entry says what happened to one target, and why: ``<Outcome> <target> -
<reason>``. A user scanning a run finds what happened in the outcome and why in
the reason, on every row and in every job. The reason is a required argument
rather than an optional suffix: a target that was skipped without saying why is
the bug this module exists to prevent.

Entries travel as structured values, so the web UI styles a row from its
outcome rather than by parsing text, and the container log writes the same
entry as one line at the outcome's level.
"""

lazy import logging
lazy from enum import StrEnum

lazy from pydantic import Field

lazy from ..schemas.base import StrictBaseModel
lazy from ..utils.time import utc_now_iso


class JobOutcome(StrEnum):
    """What a job did with one target.

    The word an entry starts with is also the counter it increments (see
    ``JobTally.outcome_counters``), so a run's totals always equal the entries
    in its log.
    """

    #: A job began a stage of work; informational, never counted.
    STARTED = "Started"
    #: Sync: a server item became a new library item.
    ADDED = "Added"
    #: Sync: an existing item's record changed.
    UPDATED = "Updated"
    #: Sync: an item already matched the server and the disk.
    UNCHANGED = "Unchanged"
    #: Sync: an item is no longer on the media server.
    REMOVED = "Removed"
    #: Assets: a download job was created.
    QUEUED = "Queued"
    #: Assets: a file was written to disk.
    DOWNLOADED = "Downloaded"
    #: Assets: a selection was saved for a local file with identical bytes;
    #: nothing was downloaded.
    ADOPTED = "Adopted"
    #: Audit: local and server assets agree.
    MATCHED = "Matched"
    #: Audit: local and server assets differ.
    MISMATCH = "Mismatch"
    #: Audit or scan: a target was inspected.
    CHECKED = "Checked"
    NO_MATCH = "No match"
    SKIPPED = "Skipped"
    ERROR = "Error"

    @property
    def log_level(self) -> int:
        """Return the container log level of an entry with this outcome."""
        return _LOG_LEVELS[self]


#: Changes to the library and findings are info; routine confirmations and
#: steps on the way to an outcome are debug; a failed target is a warning, as
#: the run carries on. The download service logs each file it writes, so a
#: run's ``Downloaded`` entry, which mirrors that write, stays at debug.
_LOG_LEVELS: frozendict[JobOutcome, int] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
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
)


class JobLogEntry(StrictBaseModel):
    """One entry of a job's progress log: what happened to a target, and why."""

    outcome: JobOutcome
    target: str
    reason: str
    at: str = Field(description="When the job wrote the entry, as an ISO timestamp.")

    def format(self) -> str:
        """Return the entry as the line the container log writes for it."""
        return f"{self.outcome} {self.target} - {self.reason}"


def log_entry(outcome: JobOutcome, target: str, reason: str) -> JobLogEntry:
    """Return the entry for one target and the reason for its outcome, stamped now."""
    return JobLogEntry(outcome=outcome, target=target, reason=reason, at=utc_now_iso())
