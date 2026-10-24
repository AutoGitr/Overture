"""The cache of the images Overture shows, kept in the config directory.

Local artwork is never shown from the media folders. Each image Overture reads
from one is kept here under the BLAKE3 hash of its bytes, the hash its art slot
records, so the cache is content-addressed:

* ``originals/xx/<hash>.jpg`` or ``.png`` holds the file exactly as it was
  read, for opening an image at full size and as the source of its thumbnail.
* ``thumbs/xx/<hash>.avif`` is the thumbnail every view shows, rendered from
  the original the first time it is asked for.

``xx`` is the hash's first byte. Entries never change once written, so a URL
that names a hash can be cached for good, and the cache can be deleted
whenever: what a slot records is read from its media folder again on demand.
"""

lazy import asyncio
lazy import os
lazy import re
lazy import stat
lazy import tempfile
lazy from collections.abc import Callable, Collection
lazy from contextlib import suppress
lazy from dataclasses import dataclass, field
lazy from pathlib import Path
lazy from typing import BinaryIO

lazy from ...domain import THUMB_BOUNDS
lazy from ...utils.assets import SAVED_EXTENSIONS
lazy from ...utils.file import compute_bytes_hash, copy_with_hash
lazy from ...utils.image import (
    SAVED_MEDIA_TYPES,
    THUMB_EXTENSION,
    inspect_saved_image,
    render_thumb,
)
lazy from ...utils.locks import KeyedLock
lazy from ...utils.path import is_within_roots, real_path
lazy from ...utils.threads import owned_thread
lazy from .assets import PathTraversalError

_ORIGINALS = "originals"
_THUMBS = "thumbs"
#: Where an entry is written before it is moved into place, so a reader never
#: finds half of one. Only entries are ever named by a hash.
_STAGING = "staging"
_HASH = re.compile(r"[0-9a-f]{64}")
#: Thumbnails rendered at once. Rendering is CPU-bound: a sidebar full of new
#: thumbnails queues here instead of occupying every worker thread.
_CONCURRENT_RENDERS = 4


def _regular_stat(path: Path) -> os.stat_result | None:
    try:
        file_stat = path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None
    return file_stat if stat.S_ISREG(file_stat.st_mode) else None


@dataclass(frozen=True, slots=True)
class CachedOriginal:
    """An image kept exactly as it was read, and the hash it is kept under."""

    file_hash: str
    path: Path
    width: int | None = field(default=None, compare=False)
    height: int | None = field(default=None, compare=False)
    stat: os.stat_result | None = field(default=None, compare=False)

    @property
    def extension(self) -> str:
        """Return the file extension the image is saved under."""
        return self.path.suffix

    @property
    def media_type(self) -> str:
        """Return the media type the image's bytes are encoded as."""
        return SAVED_MEDIA_TYPES[self.path.suffix]


class ImageCache:
    """Keep, find and prune the images shown for local artwork."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._renders = asyncio.Semaphore(_CONCURRENT_RENDERS)
        self._thumb_locks = KeyedLock[str]()

    def _entry(self, kind: str, file_hash: str, extension: str) -> Path:
        if not _HASH.fullmatch(file_hash):
            raise ValueError("An image is named by the BLAKE3 hash of its bytes")
        return self._root / kind / file_hash[:2] / f"{file_hash}{extension}"

    def _stage[T](self, write: Callable[[BinaryIO], T]) -> tuple[Path, T]:
        """Write a new entry into a file of its own before moving it into place."""
        staging = self._root / _STAGING
        staging.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=staging, suffix=".tmp")
        staged = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                written = write(stream)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
        return staged, written

    @staticmethod
    def _place(staged: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(destination)

    def _find_original(self, file_hash: str) -> CachedOriginal | None:
        if not _HASH.fullmatch(file_hash):
            return None
        for extension in SAVED_EXTENSIONS:
            path = self._entry(_ORIGINALS, file_hash, extension)
            if (file_stat := _regular_stat(path)) is not None:
                return CachedOriginal(file_hash, path, stat=file_stat)
        return None

    def has_original(self, file_hash: str) -> bool:
        """Return whether an original with this hash is kept."""
        return self._find_original(file_hash) is not None

    async def original(self, file_hash: str) -> CachedOriginal | None:
        """Return the kept original with this hash, or ``None`` when there is none."""
        return await owned_thread(self._find_original, file_hash)

    def _find_thumb(self, file_hash: str) -> tuple[Path, os.stat_result] | None:
        if not _HASH.fullmatch(file_hash):
            return None
        path = self._entry(_THUMBS, file_hash, THUMB_EXTENSION)
        if (file_stat := _regular_stat(path)) is not None:
            return path, file_stat
        return None

    def has_thumb(self, file_hash: str) -> bool:
        """Return whether a thumbnail with this hash is kept."""
        return self._find_thumb(file_hash) is not None

    async def existing_thumb(
        self, file_hash: str
    ) -> tuple[Path, os.stat_result] | None:
        """Return the kept thumbnail and its stat, or ``None`` when there is none."""
        return await owned_thread(self._find_thumb, file_hash)

    def _keep(
        self,
        staged: Path,
        file_hash: str,
        extension: str,
        width: int,
        height: int,
    ) -> CachedOriginal:
        destination = self._entry(_ORIGINALS, file_hash, extension)
        if not destination.is_file():
            self._place(staged, destination)
        return CachedOriginal(file_hash, destination, width=width, height=height)

    def _import_original(self, path: Path, root: Path) -> CachedOriginal:
        if not path.is_file():
            raise FileNotFoundError(path)
        if not is_within_roots(path, [real_path(root)]):
            raise PathTraversalError(f"Image {path} is outside {root}")
        staged, file_hash = self._stage(lambda stream: copy_with_hash(path, stream))
        try:
            extension, width, height = inspect_saved_image(staged)
            return self._keep(staged, file_hash, extension, width, height)
        finally:
            staged.unlink(missing_ok=True)

    async def import_original(self, path: Path, root: Path) -> CachedOriginal:
        """Keep the image file at *path*, which must lie inside *root*.

        Raises:
            FileNotFoundError: When *path* is not a file.
            PathTraversalError: When *path* resolves outside *root*.
            UnsupportedImageFormatError: When the file is not a readable JPEG
                or PNG within the pixel limit; nothing is kept.
            OSError: When the file cannot be read or kept.
        """
        return await owned_thread(self._import_original, path, root)

    def _store_original(self, data: bytes) -> CachedOriginal:
        extension, width, height = inspect_saved_image(data)
        file_hash = compute_bytes_hash(data)
        destination = self._entry(_ORIGINALS, file_hash, extension)
        if destination.is_file():
            return CachedOriginal(file_hash, destination, width=width, height=height)
        staged, _ = self._stage(lambda stream: stream.write(data))
        try:
            return self._keep(staged, file_hash, extension, width, height)
        finally:
            staged.unlink(missing_ok=True)

    async def store_original(self, data: bytes) -> CachedOriginal:
        """Keep the JPEG or PNG *data*.

        Raises:
            UnsupportedImageFormatError: When *data* is not a readable JPEG or
                PNG within the pixel limit; nothing is kept.
            OSError: When the image cannot be kept.
        """
        return await owned_thread(self._store_original, data)

    def _keep_thumb(self, destination: Path, data: bytes) -> None:
        staged, _ = self._stage(lambda stream: stream.write(data))
        try:
            self._place(staged, destination)
        finally:
            staged.unlink(missing_ok=True)

    async def thumb(self, original: CachedOriginal) -> Path:
        """Return the thumbnail of *original*, rendering it on first use.

        Raises:
            UnsupportedImageFormatError: When the original cannot be rendered.
            OSError: When the thumbnail cannot be kept.
        """
        path = self._entry(_THUMBS, original.file_hash, THUMB_EXTENSION)
        if await owned_thread(path.is_file):
            return path
        async with self._thumb_locks.acquire(original.file_hash):
            # Another request may have rendered it while this one waited.
            if await owned_thread(path.is_file):
                return path
            async with self._renders:
                data = await owned_thread(render_thumb, original.path, THUMB_BOUNDS)
            await owned_thread(self._keep_thumb, path, data)
        return path

    def _prune(self, keep: Collection[str], older_than: float) -> int:
        removed = 0
        for kind in (_ORIGINALS, _THUMBS):
            for shard in (self._root / kind).glob("*"):
                for path in shard.glob("*"):
                    if path.stem in keep:
                        continue
                    try:
                        if path.stat().st_mtime < older_than:
                            path.unlink()
                            removed += 1
                    except FileNotFoundError:
                        continue
                with suppress(OSError):
                    shard.rmdir()
        for path in (self._root / _STAGING).glob("*"):
            try:
                if path.stat().st_mtime < older_than:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed

    async def prune(self, keep: Collection[str], *, older_than: float) -> int:
        """Delete unkept cached image files last written before *older_than*.

        *older_than* is a time in seconds since the epoch. The age spares an
        image being kept for a slot that is not recorded yet, and a leftover
        of a write that was interrupted is removed with the rest.

        Returns:
            How many files were deleted.
        """
        return await owned_thread(self._prune, keep, older_than)
