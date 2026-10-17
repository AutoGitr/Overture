"""What a managed job counts and collects while it runs."""

lazy from collections.abc import Mapping
lazy from dataclasses import dataclass, field, fields
lazy from typing import Any, ClassVar

lazy from .progress_log import JobOutcome


@dataclass(slots=True)
class JobTally:
    """Counters and collected results for one managed job run.

    Every job reports ``done``/``total``/``errors``; a subclass adds the
    counters its own runner keeps. They are ordinary dataclass fields, so
    ``tally.skipped += 1`` is checked rather than resolved through a name
    lookup, and a mistyped counter is a type error before it is a run-time one.

    ``total`` is ``None`` while the run plans its work and is set once, by
    :meth:`ManagedJob.planned`, from the complete work list. It never changes
    after that, so ``done`` only ever climbs towards a fixed number.
    """

    done: int = 0
    total: int | None = None
    errors: int = 0

    #: The counter each progress-line outcome increments. A counter listed here
    #: is only ever changed by reporting a line, so it always equals the number
    #: of targets its lines name.
    outcome_counters: ClassVar[Mapping[JobOutcome, str]] = {JobOutcome.ERROR: "errors"}
    #: Payload key for the full collected list on terminal events.
    collect_key: ClassVar[str | None] = None
    #: Payload key for the collected length on every event.
    count_key: ClassVar[str | None] = None

    _persisted_count: int = field(default=0, init=False, repr=False)
    _collected: list[Any] = field(default_factory=list[Any], init=False, repr=False)

    @property
    def result_count(self) -> int:
        return self._persisted_count + len(self._collected)

    def drain_results(self) -> list[Any]:
        batch = self._collected
        self._persisted_count += len(batch)
        self._collected = []
        return batch

    def restore_results(self, batch: list[Any]) -> None:
        self._collected = batch + self._collected
        self._persisted_count -= len(batch)

    @property
    def collected(self) -> list[Any]:
        """Return every result collected so far."""
        return self._collected

    def collect(self, *items: Any) -> list[Any]:
        """Append results and return just the newly added ones.

        The returned slice is what a progress event should carry, so clients
        receive each result once instead of the whole list every time.
        """
        start = len(self._collected)
        self._collected.extend(items)
        return self._collected[start:]

    def count(self, outcome: JobOutcome, number: int = 1) -> None:
        """Add *number* targets to the counter *outcome* names, if any."""
        if name := self.outcome_counters.get(outcome):
            setattr(self, name, getattr(self, name) + number)

    def counters(self) -> dict[str, int | None]:
        """Return this tally's counters, in declaration order."""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if not f.name.startswith("_")
        }

    def as_payload(
        self,
        *,
        include_collected: bool = False,
        **extra: Any,
    ) -> dict[str, Any]:
        """Return counters (and optionally results) as an event payload."""
        payload: dict[str, Any] = dict(self.counters())
        if self.count_key:
            payload[self.count_key] = self._persisted_count + len(self._collected)
        if include_collected and self.collect_key:
            payload[self.collect_key] = list(self._collected)
        payload.update(extra)
        return payload


@dataclass(slots=True)
class BulkAssetTally(JobTally):
    """Counters shared by the bulk art and bulk theme runners.

    Every counter but ``settled`` equals the lines starting with its outcome.
    ``queued`` counts the downloads the run created; ``settled`` counts the
    ones that have since ended, whether ``downloaded``, ``adopted`` (identical
    to the local file, so nothing written) or failed. Matching is over long
    before the last download settles.
    """

    queued: int = 0
    downloaded: int = 0
    adopted: int = 0
    skipped: int = 0
    no_match: int = 0
    settled: int = 0

    outcome_counters: ClassVar[Mapping[JobOutcome, str]] = {
        JobOutcome.QUEUED: "queued",
        JobOutcome.DOWNLOADED: "downloaded",
        JobOutcome.ADOPTED: "adopted",
        JobOutcome.SKIPPED: "skipped",
        JobOutcome.NO_MATCH: "no_match",
        JobOutcome.ERROR: "errors",
    }


@dataclass(slots=True)
class BulkArtTally(BulkAssetTally):
    """Bulk art matching, which also streams its matches to the client."""

    collect_key: ClassVar[str | None] = "results"


@dataclass(slots=True)
class SyncTally(JobTally):
    """Library sync counters, one per outcome a synced item can have."""

    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0

    outcome_counters: ClassVar[Mapping[JobOutcome, str]] = {
        JobOutcome.ADDED: "added",
        JobOutcome.UPDATED: "updated",
        JobOutcome.UNCHANGED: "unchanged",
        JobOutcome.REMOVED: "removed",
        JobOutcome.ERROR: "errors",
    }


@dataclass(slots=True)
class AssetScanTally(JobTally):
    """Asset scan, which streams the naming issues it finds."""

    collect_key: ClassVar[str | None] = "issues"
    count_key: ClassVar[str | None] = "issues_found"


@dataclass(slots=True)
class ServerAuditTally(JobTally):
    """Server audit, which streams the mismatches it finds."""

    collect_key: ClassVar[str | None] = "results"
    count_key: ClassVar[str | None] = "results_found"


@dataclass(slots=True)
class ServerAuditFixTally(JobTally):
    """Fixing audit findings: each one ends verified, unchanged, or an error."""

    verified: int = 0
    unchanged: int = 0

    outcome_counters: ClassVar[Mapping[JobOutcome, str]] = {
        JobOutcome.MATCHED: "verified",
        JobOutcome.MISMATCH: "unchanged",
        JobOutcome.ERROR: "errors",
    }
