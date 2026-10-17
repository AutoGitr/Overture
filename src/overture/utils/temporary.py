"""Disk-backed temporary directories attributable to Overture operations."""

lazy import shutil
lazy import tempfile
lazy from collections.abc import Generator
lazy from contextlib import contextmanager
lazy from pathlib import Path

_OPERATIONS_DIR = "temporary"
_OPERATION_PREFIX = "overture-operation-"


@contextmanager
def operation_directory(config_dir: Path) -> Generator[Path]:
    """Keep bulk temporary payloads on the persistent config filesystem."""
    with create_operation_directory(config_dir) as name:
        yield Path(name)


def create_operation_directory(config_dir: Path) -> tempfile.TemporaryDirectory[str]:
    """Allocate an operation directory whose owner controls its lifetime."""
    root = config_dir / _OPERATIONS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=_OPERATION_PREFIX, dir=root)


def clean_abandoned_operations(config_dir: Path) -> None:
    """Remove only owned operation directories before runtime producers start."""
    root = (config_dir / _OPERATIONS_DIR).resolve()
    if not root.is_dir():
        return
    for candidate in root.glob(f"{_OPERATION_PREFIX}*"):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if candidate.resolve().parent == root:
            shutil.rmtree(candidate)
