"""Backup file storage and retention."""

lazy import sqlite3
lazy import zoneinfo
lazy from datetime import UTC, datetime, timedelta
lazy from pathlib import Path
lazy from typing import override

lazy import pytest

lazy from overture.schemas.backup import BackupRetention
lazy from overture.services.backup.files import (
    BackupStore,
    DatedBackup,
    retained_backups,
)

_LATEST_TWO = BackupRetention(latest=2, daily=0, weekly=0, monthly=0)


def _store(tmp_path: Path) -> BackupStore:
    return BackupStore(tmp_path / "overture.db", tmp_path / "backups")


def _create_database(store: BackupStore, journal_mode: str = "delete") -> None:
    connection = sqlite3.connect(store.database_path)
    try:
        connection.execute(f"PRAGMA journal_mode={journal_mode}")
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute(
            "CREATE TABLE auth_sessions (token_hash TEXT, id_token TEXT)"
        )
        connection.execute(
            "INSERT INTO auth_sessions VALUES ('digest', 'private-hint')"
        )
        connection.execute("INSERT INTO example (name) VALUES ('Overture')")
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
async def test_create_backup_copies_database_and_applies_retention(
    journal_mode: str, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    _create_database(store, journal_mode)
    store.directory.mkdir()
    for name in ("overture_20000101_000001.db", "overture_20000101_000002.db"):
        (store.directory / name).write_bytes(b"old")

    filename = await store.create(retention=_LATEST_TWO)
    backups = sorted(path.name for path in store.directory.iterdir())

    assert filename.startswith("overture_")
    assert filename.endswith(".db")
    assert len(backups) == 2
    assert filename in backups
    assert "overture_20000101_000001.db" not in backups

    copied = sqlite3.connect(store.directory / filename)
    try:
        row = copied.execute("SELECT name FROM example").fetchone()
        assert copied.execute("SELECT COUNT(*) FROM auth_sessions").fetchone() == (0,)
    finally:
        copied.close()
    assert row == ("Overture",)
    copy = (store.directory / filename).read_bytes()
    assert b"private-hint" not in copy
    # One self-contained file in rollback-journal mode, whatever the source's
    # mode: its header's read and write versions are 1, not WAL's 2.
    assert copy[18:20] == b"\x01\x01"


async def test_backup_without_retention_keeps_existing_backups(tmp_path: Path) -> None:
    """Pre-upgrade backups never prune what the saved schedule keeps."""
    store = _store(tmp_path)
    _create_database(store)
    store.directory.mkdir()
    old = [f"overture_20000101_00000{index}.db" for index in range(3)]
    for name in old:
        (store.directory / name).write_bytes(b"old")

    filename = await store.create(retention=None)

    assert sorted(path.name for path in store.directory.iterdir()) == sorted(
        [*old, filename]
    )


async def test_create_backup_reports_missing_database(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        await _store(tmp_path).create(retention=BackupRetention())


async def test_create_backup_filenames_do_not_collide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _create_database(store)

    class FrozenDateTime(datetime):
        @classmethod
        @override
        def now(cls, tz: object = None) -> datetime:
            del tz
            return datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=UTC)

    monkeypatch.setattr("overture.services.backup.files.datetime", FrozenDateTime)

    first = await store.create(retention=_LATEST_TWO)
    second = await store.create(retention=_LATEST_TWO)

    assert first == "overture_20260102_030405_000006.db"
    assert second == "overture_20260102_030405_000006_1.db"


async def test_create_backup_honors_configured_timezone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tz = zoneinfo.ZoneInfo("Europe/Stockholm")
    store = BackupStore(tmp_path / "overture.db", tmp_path / "backups", timezone=tz)
    _create_database(store)

    class FrozenDateTime(datetime):
        @classmethod
        @override
        def now(cls, tz: object = None) -> datetime:
            # 01:00 UTC == 03:00 Europe/Stockholm (UTC+2 in summer)
            utc_time = datetime(2026, 9, 19, 1, 0, 0, 18122, tzinfo=UTC)
            return utc_time.astimezone(tz if isinstance(tz, zoneinfo.ZoneInfo) else UTC)

    monkeypatch.setattr("overture.services.backup.files.datetime", FrozenDateTime)

    filename = await store.create(retention=_LATEST_TWO)
    assert filename == "overture_20260919_030000_018122.db"


def test_list_backups_returns_newest_first_and_ignores_other_files(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.directory.mkdir()
    first = store.directory / "overture_20000101_000001.db"
    second = store.directory / "overture_20000101_000002.db"
    ignored = store.directory / "notes.txt"
    first.write_bytes(b"1")
    second.write_bytes(b"22")
    ignored.write_text("ignore")

    result = store.list_backups()

    assert [entry.filename for entry in result] == [
        "overture_20000101_000002.db",
        "overture_20000101_000001.db",
    ]
    assert result[0].size_bytes == 2
    assert result[0].created_at


def test_prune_backups_keeps_requested_newest_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.directory.mkdir()
    for index in range(4):
        name = f"overture_20000101_00000{index}_000000.db"
        (store.directory / name).write_bytes(b"x")
    # Never pruned: Overture did not name it, so it cannot be dated.
    (store.directory / "overture_manual.db").write_bytes(b"x")

    store.prune(_LATEST_TWO)

    assert sorted(path.name for path in store.directory.iterdir()) == [
        "overture_20000101_000002_000000.db",
        "overture_20000101_000003_000000.db",
        "overture_manual.db",
    ]


def test_retention_keeps_the_newest_backup_of_each_recent_period() -> None:
    # Two backups a day, 03:00 and 15:00, for 70 days up to Sunday 2026-10-04.
    last = datetime(2026, 10, 4, 15, tzinfo=UTC)
    backups = [
        DatedBackup(taken_at, Path(taken_at.strftime("%Y%m%d_%H")))
        for taken_at in (last - timedelta(hours=12 * step) for step in range(140))
    ]

    kept = retained_backups(
        backups, BackupRetention(latest=3, daily=4, weekly=3, monthly=2)
    )

    assert sorted(path.name for path in kept) == [
        "20260920_15",  # week: ISO week 38
        "20260927_15",  # week: ISO week 39
        "20260930_15",  # month: September
        "20261001_15",  # days
        "20261002_15",
        "20261003_15",  # latest, day
        "20261004_03",  # latest
        "20261004_15",  # latest, day, week 40, month: October
    ]


def test_retention_never_prunes_the_newest_backup() -> None:
    newest = DatedBackup(datetime(2026, 10, 4, tzinfo=UTC), Path("newest"))
    older = DatedBackup(datetime(2026, 10, 3, tzinfo=UTC), Path("older"))

    assert retained_backups(
        [newest, older], BackupRetention(latest=1, daily=0, weekly=0, monthly=0)
    ) == {Path("newest")}
