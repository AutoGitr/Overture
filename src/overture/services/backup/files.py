"""Runtime-owned database backup storage."""

lazy import asyncio
lazy import logging
lazy import os
lazy import re
lazy import sqlite3
lazy import threading
lazy from collections.abc import Callable, Sequence
lazy from contextlib import closing
lazy from datetime import UTC, date, datetime, tzinfo
lazy from pathlib import Path
lazy from typing import NamedTuple

lazy from ...schemas.backup import BackupFileInfo, BackupRetention
lazy from ...utils.file import sync_directory
lazy from ...utils.threads import owned_thread

logger = logging.getLogger(__name__)

#: A backup's name carries the local time it was taken, to the second.
_BACKUP_NAME = re.compile(r"overture_(\d{8}_\d{6})(?:_\d+)*\.db")


class DatedBackup(NamedTuple):
    """A backup file and the local time it was taken."""

    taken_at: datetime
    path: Path


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
        self, *, retention: BackupRetention | None, reject_if_busy: bool = False
    ) -> str:
        """Create a backup in a worker thread with instance-wide coordination.

        Without *retention*, no existing backup is pruned.
        """
        if self._closed:
            raise RuntimeError("Backups are stopping")
        if reject_if_busy and self._async_lock.locked():
            raise BackupInProgressError("A backup is already in progress")
        async with self._async_lock:
            return await owned_thread(self._create, retention)

    async def close(self) -> None:
        """Keep ownership until the backup thread actually exits."""
        self._closed = True
        async with self._async_lock:
            pass

    async def clean_abandoned(self) -> None:
        """Remove only this store's incomplete crash leftovers before new work."""
        await owned_thread(self._clean_abandoned)

    def _clean_abandoned(self) -> None:
        for candidate in self.directory.glob("overture_*.partial"):
            if (
                not candidate.is_symlink()
                and candidate.is_file()
                and _BACKUP_NAME.fullmatch(candidate.with_suffix(".db").name)
            ):
                candidate.unlink()

    def _create(self, retention: BackupRetention | None) -> str:
        """Copy the database into the backup directory."""
        if not self.database_path.exists():
            raise RuntimeError(f"Database not found at {self.database_path}")

        with self._thread_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            filename, destination = self._next_destination()
            temporary = destination.with_suffix(".partial")
            try:
                with (
                    closing(
                        sqlite3.connect(
                            f"{self.database_path.as_uri()}?mode=ro",
                            uri=True,
                        )
                    ) as source,
                    closing(sqlite3.connect(str(temporary))) as target,
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
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                temporary.replace(destination)
            except BaseException:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        "Could not remove the partial backup %s", temporary
                    )
                raise
            sync_directory(self.directory)

            logger.info("Wrote backup %s", destination)
            if retention is not None:
                self._prune(retention)
            return filename

    def _next_destination(self) -> tuple[str, Path]:
        timestamp = datetime.now(self.timezone).strftime("%Y%m%d_%H%M%S_%f")
        stem = f"overture_{timestamp}"
        filename = f"{stem}.db"
        destination = self.directory / filename
        suffix = 1
        while destination.exists():
            filename = f"{stem}_{suffix}.db"
            destination = self.directory / filename
            suffix += 1
        return filename, destination

    def prune(self, retention: BackupRetention) -> None:
        """Delete the backups *retention* does not keep."""
        with self._thread_lock:
            self._prune(retention)

    def _dated_backups(self) -> list[DatedBackup]:
        """Return the backups this store named, newest first."""
        backups = [
            DatedBackup(
                datetime.strptime(match[1], "%Y%m%d_%H%M%S").replace(
                    tzinfo=self.timezone
                ),
                path,
            )
            for path in self.directory.iterdir()
            if (match := _BACKUP_NAME.fullmatch(path.name))
        ]
        return sorted(
            backups,
            key=lambda backup: (backup.taken_at, backup.path.name),
            reverse=True,
        )

    def _prune(self, retention: BackupRetention) -> None:
        try:
            backups = self._dated_backups()
            kept = retained_backups(backups, retention)
            for backup in backups:
                if backup.path not in kept:
                    backup.path.unlink()
                    logger.info("Removed old backup %s", backup.path)
        except OSError as exc:
            logger.warning("Could not remove old backups: %s", exc)

    def list_backups(self) -> list[BackupFileInfo]:
        """Return backups sorted newest-first."""
        try:
            with self._thread_lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                paths = sorted(
                    (
                        path
                        for path in self.directory.iterdir()
                        if _BACKUP_NAME.fullmatch(path.name)
                    ),
                    reverse=True,
                )
                return [self._file_info(path) for path in paths]
        except OSError as exc:
            logger.warning("Could not list backups: %s", exc)
            return []

    @staticmethod
    def _file_info(path: Path) -> BackupFileInfo:
        stat = path.stat()
        return BackupFileInfo(
            filename=path.name,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        )
