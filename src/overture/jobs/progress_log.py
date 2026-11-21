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
lazy from collections import Counter, defaultdict
lazy from dataclasses import dataclass, field
lazy from enum import StrEnum
lazy from typing import Any, Protocol

lazy from pydantic import Field

lazy from ..schemas.base import PublicText, StrictBaseModel
lazy from ..utils.time import utc_now_iso


class JobOutcome(StrEnum):
    """What a job did with one target.

    Every count a run reports is taken from its entries by
    :class:`OutcomeCounts`, so a run's totals always equal the targets its log
    names.
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


#: Outcomes that changed something or found something to fix; a completed run
#: with any of them has changes to announce.
CHANGE_OUTCOMES = frozenset(
    {
        JobOutcome.ADDED,
        JobOutcome.UPDATED,
        JobOutcome.REMOVED,
        JobOutcome.QUEUED,
        JobOutcome.DOWNLOADED,
        JobOutcome.ADOPTED,
        JobOutcome.MISMATCH,
    }
)

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
    reason: PublicText
    at: str = Field(description="When the job wrote the entry, as an ISO timestamp.")
    server_id: int | None = Field(
        default=None,
        description="The database's number of the media server the entry is "
        "about; none for an entry about no single server.",
    )
    server: str | None = Field(
        default=None,
        description="The MEDIA_SERVERS name of that server when the entry was written.",
    )
    count: int = Field(
        default=1,
        ge=1,
        description="How many targets the entry is about; one entry can sum up "
        "several that share an outcome and reason.",
    )

    def format(self) -> str:
        """Return the entry as the line the container log writes for it."""
        prefix = f"[{self.server}] " if self.server else ""
        return f"{prefix}{self.outcome} {self.target} - {self.reason}"


def asset_target(title: str, asset: str, *, collection: bool = False) -> str:
    """Name one asset of a title or collection, as every log names its targets.

    *asset* is the art type or ``theme``; a collection's is marked as one, so it
    never reads as the title of the same name.
    """
    return f"{title} ({'collection ' if collection else ''}{asset})"


@dataclass(frozen=True, slots=True)
class LogServer:
    """The media server a log entry is about."""

    #: The database's number of the server.
    id: int
    #: Its MEDIA_SERVERS name.
    name: str

    def on(self, entry: JobLogEntry) -> JobLogEntry:
        """Return *entry* as about this server."""
        return entry.model_copy(update={"server_id": self.id, "server": self.name})


def log_entry(
    outcome: JobOutcome,
    target: str,
    reason: str,
    *,
    server: LogServer | None = None,
    count: int = 1,
) -> JobLogEntry:
    """Return the entry for *count* targets and the reason for their outcome, now.

    *server* is the media server the entry is about, if it is about one.
    """
    entry = JobLogEntry(
        outcome=outcome, target=target, reason=reason, at=utc_now_iso(), count=count
    )
    return server.on(entry) if server is not None else entry


class Report(Protocol):
    """Write one outcome for *count* targets: a run's log, or a bare count."""

    async def __call__(
        self,
        outcome: JobOutcome,
        target: str,
        reason: str,
        /,
        *,
        count: int = 1,
        finished: bool = True,
        server: LogServer | None = None,
    ) -> None: ...


@dataclass(slots=True)
class OutcomeCounts:
    """What a run's log entries add up to: the only counts a run reports.

    Lines are what a filtered log pages through; targets are what the run's
    totals, filters and notifications show, since one line can sum up several.
    """

    lines: int = 0
    by_outcome: Counter[JobOutcome] = field(default_factory=Counter[JobOutcome])
    targets: Counter[JobOutcome] = field(default_factory=Counter[JobOutcome])
    by_server: defaultdict[int, Counter[JobOutcome]] = field(
        default_factory=lambda: defaultdict(Counter[JobOutcome])
    )

    def add(self, entry: JobLogEntry) -> None:
        """Count one entry of the run's log."""
        self.lines += 1
        self.by_outcome[entry.outcome] += 1
        self.targets[entry.outcome] += entry.count
        if entry.server_id is not None:
            self.by_server[entry.server_id][entry.outcome] += 1

    async def report(
        self,
        outcome: JobOutcome,
        target: str,
        reason: str,
        /,
        *,
        count: int = 1,
        finished: bool = True,  # noqa: ARG002 -- a bare count tracks no progress
        server: LogServer | None = None,
    ) -> None:
        """Count an outcome where no run's log is written, as :class:`Report` does."""
        self.add(log_entry(outcome, target, reason, server=server, count=count))

    def payload(self) -> dict[str, Any]:
        """Return the counts as the ``log_*`` fields of a job event."""
        return {
            "log_total": self.lines,
            "log_outcomes": dict(self.by_outcome),
            "log_targets": dict(self.targets),
            "log_servers": {
                server: dict(outcomes) for server, outcomes in self.by_server.items()
            },
        }
