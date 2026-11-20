"""Runtime-owned database backup storage."""

lazy import asyncio
lazy import logging
lazy import re
lazy import sqlite3
lazy import threading
lazy from collections.abc import Callable, Sequence
lazy from contextlib import closing
lazy from datetime import UTC, date, datetime, tzinfo
lazy from pathlib import Path
lazy from typing import NamedTuple

lazy from ...schemas.backup import (
    BackupCreatedResponse,
    BackupFileInfo,
    BackupRetention,
)
lazy from ...utils.file import staged_file, staged_leftovers, sync_directory
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import local_now

logger = logging.getLogger(__name__)

#: A backup's name carries the local time it was taken, to the second, and
#: the schema revision an upgrade started from when it was taken before one.
_BACKUP_NAME = re.compile(
    r"overture_(\d{8}_\d{6})(?:_\d+)*(?:_before_([0-9a-z]+))?\.db"
)


class DatedBackup(NamedTuple):
    """A backup file and the local time it was taken."""

    taken_at: datetime
    path: Path
    #: The schema revision an upgrade started from, for a backup taken before one.
    before: str | None = None


def _day(taken_at: datetime) -> date:
    return taken_at.date()


def _week(taken_at: datetime) -> tuple[int, int]:
    year, week, _ = taken_at.isocalendar()
    return year, week


def _month(taken_at: datetime) -> tuple[int, int]:
    return taken_at.year, taken_at.month


def retained_backups(
    backups: Sequence[DatedBackup], retention: BackupRetention
) -> set[Path]:
    """Return the backups *retention* keeps out of *backups*, given newest first."""
    kept = {backup.path for backup in backups[: retention.latest]}
    periods: tuple[tuple[int, Callable[[datetime], object]], ...] = (
        (retention.daily, _day),
        (retention.weekly, _week),
        (retention.monthly, _month),
    )
    for count, period in periods:
        seen: set[object] = set()
        for backup in backups:
            if len(seen) == count:
                break
            key = period(backup.taken_at)
            if key not in seen:
                seen.add(key)
                kept.add(backup.path)
    return kept


class BackupInProgressError(RuntimeError):
    """Raised when a backup is requested while one is already running."""


class BackupStore:
    """Create, retain, and list backups for one database and destination."""

    def __init__(
        self,
        database_path: Path,
        directory: Path,
        *,
        timezone: tzinfo = UTC,
    ) -> None:
        self.database_path = database_path
        self.directory = directory
        self.timezone = timezone
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.Lock()
        self._closed = False

    async def create(
        self,
        *,
        retention: BackupRetention | None,
        reject_if_busy: bool = False,
        before: str | None = None,
    ) -> BackupCreatedResponse:
        """Create a backup in a worker thread with instance-wide coordination.

        Without *retention*, no existing backup is pruned. A backup taken
        *before* upgrading from a revision replaces any taken before it earlier.
        """
        if self._closed:
            raise RuntimeError("Backups are stopping")
        if reject_if_busy and self._async_lock.locked():
            raise BackupInProgressError("A backup is already in progress")
        async with self._async_lock:
            return await owned_thread(self._create, retention, before)

    async def close(self) -> None:
        """Keep ownership until the backup thread actually exits."""
        self._closed = True
        async with self._async_lock:
            pass

    async def clean_abandoned(self) -> None:
        """Remove only this store's incomplete crash leftovers before new work."""
        await owned_thread(self._clean_abandoned)

    def _clean_abandoned(self) -> None:
        if self.directory.is_dir():
            for leftover in staged_leftovers(self.directory):
                leftover.unlink(missing_ok=True)

    def _create(
        self, retention: BackupRetention | None, before: str | None
    ) -> BackupCreatedResponse:
        """Copy the database into the backup directory."""
        if not self.database_path.exists():
            raise RuntimeError(f"Database not found at {self.database_path}")

        with self._thread_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            filename, destination = self._next_destination(before)
            with staged_file(self.directory) as staged:
                # SQLite writes the copy itself, through the staged file's path.
                with (
                    closing(
                        sqlite3.connect(
                            f"{self.database_path.as_uri()}?mode=ro",
                            uri=True,
                        )
                    ) as source,
                    closing(sqlite3.connect(staged.path)) as target,
                ):
                    source.backup(target)
                    # The copy inherits the source's WAL mode, where the delete
                    # below reaches the file only if closing checkpoints it.
                    # A rollback journal writes it into the file on commit.
                    target.execute("PRAGMA journal_mode=DELETE")
                    # Restoring application data must never resurrect revoked logins.
                    target.execute("PRAGMA secure_delete=ON")
                    target.execute("DELETE FROM auth_sessions")
                    target.commit()
                    if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise RuntimeError("Backup integrity check failed")
                staged.place(destination)
            removed = self._replaced(destination, before) if before else []
            if removed:
                sync_directory(self.directory)

            logger.info("Wrote backup %s", destination)
            if retention is not None:
                removed += self._prune(retention)
            return BackupCreatedResponse(filename=filename, removed=removed)

    def _next_destination(self, before: str | None) -> tuple[str, Path]:
        timestamp = local_now(self.timezone).strftime("%Y%m%d_%H%M%S_%f")
        stem = f"overture_{timestamp}"
        upgrade = f"_before_{before}" if before else ""
        filename = f"{stem}{upgrade}.db"
        destination = self.directory / filename
        suffix = 1
        while destination.exists():
            filename = f"{stem}_{suffix}{upgrade}.db"
            destination = self.directory / filename
            suffix += 1
        return filename, destination

    def _replaced(self, kept: Path, before: str) -> list[str]:
        """Delete the other backups taken before upgrading from *before*."""
        removed: list[str] = []
        for backup in self._dated_backups():
            if backup.before == before and backup.path != kept:
                backup.path.unlink(missing_ok=True)
                removed.append(backup.path.name)
                logger.info("Replaced backup %s", backup.path)
        return removed

    async def prune(self, retention: BackupRetention) -> list[str]:
        """Delete the backups *retention* does not keep; return their names."""
        async with self._async_lock:
            return await owned_thread(self._locked_prune, retention)

    def _locked_prune(self, retention: BackupRetention) -> list[str]:
        with self._thread_lock:
            return self._prune(retention)

    def _dated_backups(self) -> list[DatedBackup]:
        """Return the backups this store named, newest first."""
        backups = [
            DatedBackup(
                datetime.strptime(match[1], "%Y%m%d_%H%M%S").replace(
                    tzinfo=self.timezone
                ),
                path,
                match[2],
            )
            for path in self.directory.iterdir()
            if (match := _BACKUP_NAME.fullmatch(path.name))
        ]
        return sorted(
            backups,
            key=lambda backup: (backup.taken_at, backup.path.name),
            reverse=True,
        )

    def _prune(self, retention: BackupRetention) -> list[str]:
        removed: list[str] = []
        try:
            backups = self._dated_backups()
            kept = retained_backups(backups, retention)
            for backup in backups:
                if backup.path not in kept:
                    backup.path.unlink()
                    removed.append(backup.path.name)
                    logger.info("Removed old backup %s", backup.path)
        except OSError as exc:
            logger.warning("Could not remove old backups: %s", exc)
        return removed

    def list_backups(self) -> list[BackupFileInfo]:
        """Return backups newest first, dated by the time in their name."""
        try:
            with self._thread_lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                return [
                    BackupFileInfo(
                        filename=backup.path.name,
                        size_bytes=backup.path.stat().st_size,
                        created_at=backup.taken_at.isoformat(),
                    )
                    for backup in self._dated_backups()
                ]
        except OSError as exc:
            logger.warning("Could not list backups: %s", exc)
            return []
