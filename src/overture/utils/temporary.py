"""Disk-backed temporary directories attributable to Overture operations."""

lazy import shutil
lazy import tempfile
lazy from collections.abc import Generator
lazy from contextlib import contextmanager, suppress
lazy from pathlib import Path
lazy from typing import override

_OPERATIONS_DIR = ".tmp"
_OPERATION_PREFIX = "overture-operation-"


def _clean_empty_root(config_dir: Path) -> None:
    with suppress(OSError):
        (config_dir / _OPERATIONS_DIR).rmdir()


class _OperationDirectory(tempfile.TemporaryDirectory[str]):
    """An operation directory that cleans up the empty root on release."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        root = config_dir / _OPERATIONS_DIR
        root.mkdir(parents=True, exist_ok=True)
        super().__init__(prefix=_OPERATION_PREFIX, dir=root)

    @override
    def cleanup(self) -> None:
        super().cleanup()
        _clean_empty_root(self._config_dir)


@contextmanager
def operation_directory(config_dir: Path) -> Generator[Path]:
    """Keep bulk temporary payloads on the persistent config filesystem."""
    with create_operation_directory(config_dir) as name:
        yield Path(name)


def create_operation_directory(config_dir: Path) -> tempfile.TemporaryDirectory[str]:
    """Allocate an operation directory whose owner controls its lifetime."""
    return _OperationDirectory(config_dir)


def clean_abandoned_operations(config_dir: Path) -> None:
    """Remove only owned operation directories before runtime producers start."""
    root = (config_dir / _OPERATIONS_DIR).resolve()
    if not root.is_dir():
        return
    for candidate in root.glob(f"{_OPERATION_PREFIX}*"):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if candidate.resolve().parent == root:
            shutil.rmtree(candidate, ignore_errors=True)
    with suppress(OSError):
        root.rmdir()
