"""The images Overture shows, kept in the config directory.

Local artwork is never shown from the media folders. Each image is kept under
the BLAKE3 hash of its bytes, the hash its art slot records, in one of two
content-addressed folders, where ``xx`` is the hash's first byte:

* The cache holds ``originals/xx/<hash>.jpg`` or ``.png``, each file exactly
  as it was read, and ``thumbs/xx/<hash>.avif``, the thumbnail every view
  shows, rendered from the original the first time it is asked for. It can be
  deleted whenever: a media folder's image is read again on demand, a link
  fetched again and generated art drawn again.
* The uploads hold ``xx/<hash>.jpg`` or ``.png``, the images people uploaded.
  Overture holds their only copy, so it never deletes one.

Entries never change once written, so a URL that names a hash can be cached
for good. Reading an original looks in the uploads first.
"""

lazy import asyncio
lazy import os
lazy import re
lazy import shutil
lazy import stat
lazy from collections.abc import Collection
lazy from contextlib import suppress
lazy from dataclasses import dataclass, field
lazy from pathlib import Path

lazy from ...domain import THUMB_BOUNDS
lazy from ...utils.assets import SAVED_EXTENSIONS
lazy from ...utils.file import staged_file, staged_leftovers
lazy from ...utils.hashing import compute_bytes_hash, compute_file_hash, copy_with_hash
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
#: finds half of one. Each folder stages its own, so placing an entry is a
#: rename within one filesystem. Only entries are ever named by a hash.
_STAGING = "staging"
_UPLOAD_STAGING = ".staging"
#: The cache's own folder in Overture 0.3 and earlier, which held the uploads.
_LEGACY = "images"
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


@dataclass(frozen=True, slots=True)
class CacheUsage:
    """How many files one part of the cache holds, and their bytes."""

    files: int = 0
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ImageCacheUsage:
    """What the cache and the uploads hold on disk."""

    originals: CacheUsage
    thumbs: CacheUsage
    uploads: CacheUsage


class ImageCache:
    """Keep, find and prune the images shown for local artwork."""

    def __init__(self, root: Path, uploads: Path) -> None:
        self._root = root
        self._uploads = uploads
        self._renders = asyncio.Semaphore(_CONCURRENT_RENDERS)
        self._thumb_locks = KeyedLock[str]()

    def _entry(self, kind: str, file_hash: str, extension: str) -> Path:
        if not _HASH.fullmatch(file_hash):
            raise ValueError("An image is named by the BLAKE3 hash of its bytes")
        return self._root / kind / file_hash[:2] / f"{file_hash}{extension}"

    def _upload_entry(self, file_hash: str, extension: str) -> Path:
        if not _HASH.fullmatch(file_hash):
            raise ValueError("An image is named by the BLAKE3 hash of its bytes")
        return self._uploads / file_hash[:2] / f"{file_hash}{extension}"

    def _find_original(self, file_hash: str) -> CachedOriginal | None:
        if not _HASH.fullmatch(file_hash):
            return None
        for extension in SAVED_EXTENSIONS:
            for path in (
                self._upload_entry(file_hash, extension),
                self._entry(_ORIGINALS, file_hash, extension),
            ):
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

    def _import_original(self, path: Path, root: Path) -> CachedOriginal:
        if not path.is_file():
            raise FileNotFoundError(path)
        if not is_within_roots(path, [real_path(root)]):
            raise PathTraversalError(f"Image {path} is outside {root}")
        with staged_file(self._root / _STAGING) as staged:
            file_hash = copy_with_hash(path, staged.stream)
            staged.finish()
            extension, width, height = inspect_saved_image(staged.path)
            destination = self._entry(_ORIGINALS, file_hash, extension)
            # An entry is named by the hash of its bytes, so one already
            # there holds these.
            if not destination.is_file():
                staged.place(destination)
        return CachedOriginal(file_hash, destination, width=width, height=height)

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

    def _store(self, data: bytes, *, upload: bool) -> CachedOriginal:
        extension, width, height = inspect_saved_image(data)
        file_hash = compute_bytes_hash(data)
        if upload:
            destination = self._upload_entry(file_hash, extension)
            staging = self._uploads / _UPLOAD_STAGING
        else:
            destination = self._entry(_ORIGINALS, file_hash, extension)
            staging = self._root / _STAGING
        # An upload is the only copy, so one that does not hold its bytes, as
        # a crash may leave, is written again; a cached copy can be fetched.
        if (
            compute_file_hash(destination) != file_hash
            if upload
            else not destination.is_file()
        ):
            with staged_file(staging) as staged:
                staged.stream.write(data)
                staged.place(destination)
        return CachedOriginal(file_hash, destination, width=width, height=height)

    async def store_original(self, data: bytes) -> CachedOriginal:
        """Keep the JPEG or PNG *data* in the cache.

        Raises:
            UnsupportedImageFormatError: When *data* is not a readable JPEG or
                PNG within the pixel limit; nothing is kept.
            OSError: When the image cannot be kept.
        """
        return await owned_thread(self._store, data, upload=False)

    async def store_upload(self, data: bytes) -> CachedOriginal:
        """Keep the uploaded JPEG or PNG *data* for good.

        Raises:
            UnsupportedImageFormatError: When *data* is not a readable JPEG or
                PNG within the pixel limit; nothing is kept.
            OSError: When the image cannot be kept.
        """
        return await owned_thread(self._store, data, upload=True)

    def _adopt_uploads(self, hashes: Collection[str]) -> int:
        legacy = self._root / _LEGACY
        moved = 0
        for file_hash in hashes:
            if not _HASH.fullmatch(file_hash):
                continue
            for extension in SAVED_EXTENSIONS:
                destination = self._upload_entry(file_hash, extension)
                for cached in (
                    legacy / _ORIGINALS / file_hash[:2] / f"{file_hash}{extension}",
                    self._entry(_ORIGINALS, file_hash, extension),
                ):
                    if _regular_stat(cached) is None:
                        continue
                    # The cached copy may be the only one, so it goes only once
                    # an upload holding its bytes is on disk; one a crash left
                    # partly written is written again.
                    if compute_file_hash(destination) != file_hash:
                        if compute_file_hash(cached) != file_hash:
                            continue
                        with staged_file(self._uploads / _UPLOAD_STAGING) as staged:
                            copy_with_hash(cached, staged.stream)
                            staged.place(destination)
                        moved += 1
                    cached.unlink()
        if legacy.is_dir():
            for kind in (_ORIGINALS, _THUMBS):
                if (legacy / kind).is_dir() and not (self._root / kind).exists():
                    (legacy / kind).rename(self._root / kind)
            shutil.rmtree(legacy)
        return moved

    async def adopt_uploads(self, hashes: Collection[str]) -> int:
        """Move the uploads *hashes* names out of the cache; return how many moved.

        Overture 0.3 and earlier kept uploads in the cache, in its own
        ``images`` folder, which this also takes the rest of the cache out of.
        """
        return await owned_thread(self._adopt_uploads, hashes)

    def _keep_thumb(self, destination: Path, data: bytes) -> None:
        with staged_file(self._root / _STAGING) as staged:
            staged.stream.write(data)
            staged.place(destination)

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
        # A staged file is a write that was interrupted, never an entry.
        for staging in (self._root / _STAGING, self._uploads / _UPLOAD_STAGING):
            # Only old ones go: a write may be staging one now.
            for path in staged_leftovers(staging) if staging.is_dir() else []:
                try:
                    if path.stat().st_mtime < older_than:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
        return removed

    @staticmethod
    def _usage_of(folder: Path) -> CacheUsage:
        sizes = [
            file_stat.st_size
            for path in folder.glob("*/*")
            if _HASH.fullmatch(path.stem)
            and (file_stat := _regular_stat(path)) is not None
        ]
        return CacheUsage(files=len(sizes), size_bytes=sum(sizes))

    def _usage(self) -> ImageCacheUsage:
        return ImageCacheUsage(
            originals=self._usage_of(self._root / _ORIGINALS),
            thumbs=self._usage_of(self._root / _THUMBS),
            uploads=self._usage_of(self._uploads),
        )

    async def usage(self) -> ImageCacheUsage:
        """Count the cached originals and thumbnails, the uploads, and their bytes."""
        return await owned_thread(self._usage)

    async def prune(self, keep: Collection[str], *, older_than: float) -> int:
        """Delete unkept cached image files last written before *older_than*.

        The uploads are never deleted.

        *older_than* is a time in seconds since the epoch. The age spares an
        image being kept for a slot that is not recorded yet, and a leftover
        of a write that was interrupted is removed with the rest.

        Returns:
            How many files were deleted.
        """
        return await owned_thread(self._prune, keep, older_than)
