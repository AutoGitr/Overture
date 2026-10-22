"""Tests for temporary operations directories."""

lazy from pathlib import Path

lazy from overture.utils.temporary import (
    clean_abandoned_operations,
    create_operation_directory,
    operation_directory,
)


def test_operation_directory_removes_root_when_empty(tmp_path: Path) -> None:
    assert not (tmp_path / ".tmp").exists()
    with operation_directory(tmp_path) as op_dir:
        assert op_dir.is_dir()
        assert (tmp_path / ".tmp").is_dir()
        (op_dir / "file.txt").write_text("content")

    # Once the context exits, the op directory and empty root are cleaned up
    assert not (tmp_path / ".tmp").exists()


def test_create_operation_directory_cleanup_removes_root_when_empty(
    tmp_path: Path,
) -> None:
    assert not (tmp_path / ".tmp").exists()
    op = create_operation_directory(tmp_path)
    op_path = Path(op.name)
    assert op_path.is_dir()
    assert (tmp_path / ".tmp").is_dir()

    op.cleanup()
    assert not op_path.exists()
    assert not (tmp_path / ".tmp").exists()


def test_clean_abandoned_operations_removes_only_owned_temp_dirs(
    tmp_path: Path,
) -> None:
    # 1. Real database/config files in config_dir must NEVER be touched
    db_file = tmp_path / "overture.db"
    db_file.write_text("sqlite database")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "backup.db").write_text("backup")

    # 2. Setup .tmp with abandoned operation and unrelated files
    tmp_root = tmp_path / ".tmp"
    tmp_root.mkdir()

    abandoned = tmp_root / "overture-operation-12345"
    abandoned.mkdir()
    (abandoned / "temp.bin").write_bytes(b"data")

    # Unrelated files or folders inside .tmp must NEVER be deleted
    unrelated_file = tmp_root / "custom.txt"
    unrelated_file.write_text("keep me")
    unrelated_dir = tmp_root / "other-dir"
    unrelated_dir.mkdir()

    clean_abandoned_operations(tmp_path)

    # Abandoned op is cleaned up
    assert not abandoned.exists()

    # Unrelated items and config files are completely untouched
    assert unrelated_file.exists()
    assert unrelated_dir.exists()
    assert db_file.exists()
    assert backup_dir.exists()
    # .tmp is preserved because it still contains unrelated items
    assert tmp_root.exists()

    # Once unrelated items are removed, clean_abandoned_operations cleans the empty root
    unrelated_file.unlink()
    unrelated_dir.rmdir()
    clean_abandoned_operations(tmp_path)
    assert not tmp_root.exists()
