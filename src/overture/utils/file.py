"""Generic filesystem utility functions."""

lazy import errno
lazy import logging
lazy import os
lazy from pathlib import Path
lazy from typing import BinaryIO

lazy from blake3 import blake3 as _blake3

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: str | Path) -> str | None:
    """Compute BLAKE3 hash of a file in chunks.

    Returns None if the file cannot be read.
    """
    try:
        hasher = _blake3()
        with Path(file_path).open("rb") as f:
            for chunk in iter(lambda: f.read(65_536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as exc:
        logger.debug("Could not hash a file: %s", exc)
        return None


def copy_with_hash(source: Path, destination: BinaryIO) -> str:
    """Copy *source* into *destination* and return the BLAKE3 hash of what was copied.

    The hash and the copy come from the same bytes, so they agree even when
    *source* changes while it is read.
    """
    hasher = _blake3()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            hasher.update(chunk)
            destination.write(chunk)
    return hasher.hexdigest()


def compute_bytes_hash(data: bytes) -> str:
    """Compute BLAKE3 hash of an in-memory byte buffer."""
    return _blake3(data).hexdigest()


def sync_directory(path: Path) -> None:
    """Persist a completed rename on filesystems that support directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
            raise
    finally:
        os.close(descriptor)
