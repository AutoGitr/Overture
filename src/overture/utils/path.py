"""Generic filesystem path validation helpers."""

lazy import os
lazy from collections.abc import Collection
lazy from pathlib import Path


def real_path(path: str | Path) -> str:
    """Resolve symlinks and relative components for a filesystem path."""
    return str(Path(path).resolve())


def is_within_roots(path: str | Path, roots: Collection[str | Path]) -> bool:
    """Return True when *path* resolves inside one of *roots*.

    The roots must already be resolved with :func:`real_path`; only *path* is
    resolved here, so checking many paths costs no stats per root.
    """
    try:
        candidate = Path(real_path(path))
    except OSError, ValueError:
        return False
    return any(candidate.is_relative_to(root) for root in roots)


def same_revision(before: os.stat_result, after: os.stat_result) -> bool:
    """Return whether two stats of a path describe the same file revision.

    A file read between them is only trusted when they do, so its contents
    are never paired with another revision's stat.
    """
    return (before.st_mtime_ns, before.st_size, before.st_ino) == (
        after.st_mtime_ns,
        after.st_size,
        after.st_ino,
    )
