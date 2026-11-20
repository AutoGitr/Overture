"""Every hash Overture takes: of file contents, and digests of text.

Content hashes are BLAKE3 and name what they hash: an image kept in the cache
or uploads is stored under the hash of its bytes, and a local file is known
unchanged by it. Text digests are SHA-256, which stored values depend on:
signed-in sessions keep their token's digest, and Plex labels and image
versions carry a short one, so neither may change.
"""

lazy import hashlib
lazy import logging
lazy from pathlib import Path
lazy from typing import BinaryIO

lazy from blake3 import blake3

logger = logging.getLogger(__name__)

_CHUNK = 65_536


def compute_bytes_hash(data: bytes) -> str:
    """Return the content hash of *data*."""
    return blake3(data).hexdigest()


def compute_file_hash(file_path: str | Path) -> str | None:
    """Return the content hash of a file, read in chunks; ``None`` if unreadable."""
    try:
        hasher = blake3()
        with Path(file_path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as exc:
        logger.debug("Could not hash a file: %s", exc)
        return None


def copy_with_hash(source: Path, destination: BinaryIO) -> str:
    """Copy *source* into *destination* and return the content hash of the copy.

    The hash and the copy come from the same bytes, so they agree even when
    *source* changes while it is read.
    """
    hasher = blake3()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            hasher.update(chunk)
            destination.write(chunk)
    return hasher.hexdigest()


def text_digest(text: str, length: int | None = None) -> str:
    """Return the SHA-256 digest of *text*, cut to its first *length* characters."""
    return hashlib.sha256(text.encode()).hexdigest()[:length]
