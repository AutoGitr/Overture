"""Writing the files Overture keeps, so a crash leaves each whole.

Every file Overture keeps is written beside its destination, synced, and moved
into place with a synced rename. Scratch files in an operation's own directory
(:mod:`overture.utils.temporary`) need none of that.
"""

lazy import errno
lazy import logging
lazy import os
lazy import tempfile
lazy from collections.abc import Generator
lazy from contextlib import contextmanager
lazy from pathlib import Path
lazy from typing import BinaryIO

logger = logging.getLogger(__name__)


def process_owner() -> str:
    """Name the user and group this process writes files as, for permission errors."""
    if os.name == "nt":
        return "the current Windows user"
    return f"UID={os.getuid()} GID={os.getgid()}"


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


#: How a staged file is named: hidden, and never like a file anything reads.
_STAGED_PREFIX = "."
_STAGED_SUFFIX = ".tmp"


def staged_leftovers(directory: Path) -> list[Path]:
    """The files staged in *directory* and never placed.

    Each is a write that failed or a crash interrupted; one being written now
    looks the same, so remove them only where no write can be running.
    """
    return [
        path
        for path in directory.glob(f"{_STAGED_PREFIX}*{_STAGED_SUFFIX}")
        if path.is_file() and not path.is_symlink()
    ]


class StagedFile:
    """A new file written beside where it goes, until it is placed there."""

    def __init__(self, path: Path, stream: BinaryIO) -> None:
        self.path = path
        self.stream = stream
        self.placed = False

    def finish(self) -> None:
        """Flush and sync what was written and close the file; safe to repeat."""
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()

    def place(self, destination: Path) -> None:
        """Move the finished file to *destination*, replacing it in one step.

        The rename is synced to its directory before returning, so a crash
        leaves the old file or the new one, whole. *destination* must be on
        the staging directory's filesystem.
        """
        self.finish()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.path.replace(destination)
        self.placed = True
        sync_directory(destination.parent)


@contextmanager
def staged_file(directory: Path, *, mode: int = 0o644) -> Generator[StagedFile]:
    """Open a new file in *directory* to write and then place somewhere.

    Unless it was placed by the end of the block, it is removed, so neither a
    failure nor a crash leaves a partial file under a name anything reads.
    """
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=directory, prefix=_STAGED_PREFIX, suffix=_STAGED_SUFFIX
    )
    path = Path(name)
    try:
        path.chmod(mode)
        staged = StagedFile(path, os.fdopen(descriptor, "wb"))
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    try:
        yield staged
    finally:
        staged.stream.close()
        if not staged.placed:
            path.unlink(missing_ok=True)
