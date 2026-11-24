"""What a managed job counts and collects while it runs."""

lazy from dataclasses import dataclass, field, fields
lazy from typing import Any, ClassVar

lazy from ..schemas.base import StrictBaseModel


@dataclass(slots=True)
class JobTally:
    """Progress and collected results for one managed job run.

    ``total`` is ``None`` while the run plans its work, counting what it
    reads in ``read``, and is set once, by :meth:`ManagedJob.planned`, from
    the complete work list. It never changes after that, so ``done`` only
    ever climbs towards a fixed number. Counts of outcomes are not kept here:
    the run's log entries are the only source of them
    (:class:`~overture.jobs.progress_log.OutcomeCounts`).
    """

    done: int = 0
    total: int | None = None
    #: Targets read while the run plans, which shows it working until the
    #: total is known.
    read: int = 0

    #: Payload key for the full collected list on terminal events.
    collect_key: ClassVar[str | None] = None
    #: Payload key for the collected length on every event.
    count_key: ClassVar[str | None] = None

    _persisted_count: int = field(default=0, init=False, repr=False)
    _collected: list[StrictBaseModel] = field(
        default_factory=list[StrictBaseModel], init=False, repr=False
    )

    @property
    def result_count(self) -> int:
        return self._persisted_count + len(self._collected)

    def drain_results(self) -> list[StrictBaseModel]:
        batch = self._collected
        self._persisted_count += len(batch)
        self._collected = []
        return batch

    def restore_results(self, batch: list[StrictBaseModel]) -> None:
        self._collected = batch + self._collected
        self._persisted_count -= len(batch)

    @property
    def collected(self) -> list[StrictBaseModel]:
        """Return every result collected so far."""
        return self._collected

    def collect(self, *items: StrictBaseModel) -> list[StrictBaseModel]:
        """Append results and return just the newly added ones.

        The returned slice is what a progress event should carry, so clients
        receive each result once instead of the whole list every time.
        """
        start = len(self._collected)
        self._collected.extend(items)
        return self._collected[start:]

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
    """Assets runs, whose queued downloads settle after matching is over.

    ``settled`` counts the downloads that have since ended, whether
    downloaded or failed.
    """

    settled: int = 0


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
