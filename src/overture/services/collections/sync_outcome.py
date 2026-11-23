"""What one collection's sync did on each media server, as its job log tells it."""

lazy from collections.abc import Callable, Iterable
lazy from dataclasses import dataclass, field
lazy from typing import Self

lazy from ...jobs.progress_log import JobOutcome, LogServer, Report
lazy from ...media_servers.errors import MediaServerError
lazy from .copies import ServerCopy


def _titles(count: int) -> str:
    return f"{count} title{'' if count == 1 else 's'}"


@dataclass(slots=True)
class CopyChange:
    """What a sync did to one server collection of a collection."""

    #: The database's number of its server.
    server_id: int
    #: The libraries whose members it holds.
    library_ids: tuple[str, ...]
    #: The sync made it.
    created: bool = False
    #: Members the sync put in and took out.
    added: int = 0
    removed: int = 0
    #: How many members it holds after the sync.
    held: int = 0
    #: Why the sync deleted it; ``None`` while it stays.
    deleted: str | None = None
    #: There is none, as no title in its libraries meets the rule.
    absent: bool = False
    #: Why its server refused the sync; ``None`` when it took it.
    error: str | None = None

    @classmethod
    def failed(cls, copy: ServerCopy, exc: MediaServerError) -> Self:
        """The change a server that refused *copy*'s sync made: none."""
        return cls(copy.server_id, copy.library_order, error=exc.message)

    def entry(self, libraries: str) -> tuple[JobOutcome, str]:
        """The outcome and reason of the change, *libraries* naming where it is."""
        if self.error is not None:
            return JobOutcome.ERROR, f"not synced in {libraries}: {self.error}"
        if self.deleted is not None:
            return JobOutcome.REMOVED, f"deleted from {libraries}: {self.deleted}"
        if self.absent:
            return JobOutcome.SKIPPED, (
                f"not created in {libraries}: no title there meets its rule"
            )
        if self.created:
            return JobOutcome.ADDED, f"created in {libraries} with {_titles(self.held)}"
        if self.added or self.removed:
            return JobOutcome.UPDATED, (
                f"{self.added} added and {self.removed} removed in {libraries}, "
                f"leaving {_titles(self.held)}"
            )
        return JobOutcome.UNCHANGED, (
            f"holds the same {_titles(self.held)} in {libraries}"
        )


@dataclass(slots=True)
class SyncOutcome:
    """What one collection's sync did, server collection by server collection."""

    changes: list[CopyChange] = field(default_factory=list[CopyChange])
    #: Why the sync left the collection as it was, or off every server.
    held_back: str | None = None
    #: The sync left the servers' copies as they were.
    skipped: bool = False
    #: The collection is off the servers, below its minimum or out of season.
    withheld: bool = False
    #: The names of the libraries its changes name, by ID.
    library_names: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def errors(self) -> str | None:
        """Why servers refused their copies' sync; ``None`` when none did."""
        return "; ".join(c.error for c in self.changes if c.error is not None) or None

    def record(self, changes: Iterable[CopyChange]) -> None:
        """Add *changes*; a failure joins the entry of the copy it happened to."""
        for change in changes:
            same = next(
                (
                    held
                    for held in self.changes
                    if (held.server_id, held.library_ids)
                    == (change.server_id, change.library_ids)
                ),
                None,
            )
            if same is None:
                self.changes.append(change)
            elif same.error is None:
                same.error = change.error

    def deleted(
        self, copies: Iterable[tuple[int, tuple[str, ...]]], reason: str
    ) -> None:
        """Record server collections, by server and libraries, deleted for *reason*."""
        self.changes.extend(
            CopyChange(server_id, library_ids, deleted=reason)
            for server_id, library_ids in copies
        )

    async def report(
        self,
        report: Report,
        title: str,
        servers: Callable[[int], LogServer],
    ) -> None:
        """Write one entry for each server collection the sync touched.

        *servers* names a server by its database number.
        """
        for change in self.changes:
            outcome, reason = change.entry(
                ", ".join(self.library_names.get(i, i) for i in change.library_ids)
            )
            await report(
                outcome,
                title,
                reason,
                finished=False,
                server=servers(change.server_id),
            )
        if self.held_back is not None:
            await report(JobOutcome.SKIPPED, title, self.held_back, finished=False)
