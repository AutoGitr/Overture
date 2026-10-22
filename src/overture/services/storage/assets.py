"""Local asset discovery, target resolution, and filesystem writes."""

lazy import logging
lazy import os
lazy import stat
lazy import tempfile
lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ITEM_ART_TYPES, ArtType
lazy from ...utils.assets import (
    IMAGE_EXTENSIONS,
    ITEM_ASSET_CANDIDATES,
    THEME_FILENAME,
    season_poster_candidates,
    season_poster_filename,
)
lazy from ...utils.file import compute_bytes_hash, compute_file_hash, sync_directory
lazy from ...utils.locks import KeyedLock
lazy from ...utils.path import same_revision
lazy from ...utils.threads import owned_thread

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredFile:
    """The hash and stat revision of one asset file, taken together."""

    file_hash: str
    mtime_ns: int
    size: int


class PathTraversalError(Exception):
    """Raised when a resolved path escapes allowed boundaries."""


class TargetDirectoryMissingError(Exception):
    """Raised when a file write target directory does not exist."""


class MissingLocalPathError(Exception):
    """Raised when a server-only item is used for a local file operation."""


def require_folder_path(item: MediaItem) -> str:
    """Return an item's local folder path or raise a clear local-file error."""
    if not item.folder_path:
        raise MissingLocalPathError(
            "Item has no folder_path; local file operations require "
            "a media-server item with a filesystem path."
        )
    return item.folder_path


class FolderListing:
    """Answer which files and folders exist, listing each folder once.

    A lookup reads its folder with one ``scandir`` on first use and answers
    every later lookup in that folder from it, so finding an item's artwork,
    theme and season folders costs one listing per folder instead of a stat
    per candidate name. Use one listing for one inspection: it never sees
    changes made after a folder was read.
    """

    def __init__(self) -> None:
        self._folders: dict[Path, dict[str, os.DirEntry[str]]] = {}
        self._stats: dict[Path, os.stat_result | None] = {}

    def _entry(self, path: Path) -> os.DirEntry[str] | None:
        folder = path.parent
        entries = self._folders.get(folder)
        if entries is None:
            try:
                with os.scandir(folder) as listing:
                    entries = {entry.name: entry for entry in listing}
            except FileNotFoundError, NotADirectoryError:
                entries = {}
            self._folders[folder] = entries
        return entries.get(path.name)

    def is_file(self, path: Path) -> bool:
        """Only confirmed absence is absence; propagate unavailable storage."""
        entry = self._entry(path)
        return entry is not None and entry.is_file()

    def is_dir(self, path: Path) -> bool:
        """Return whether *path* is a directory, following symlinks."""
        entry = self._entry(path)
        return entry is not None and entry.is_dir()

    def _stat(self, path: Path) -> os.stat_result | None:
        if path not in self._stats:
            try:
                self._stats[path] = path.stat()
            except FileNotFoundError, NotADirectoryError:
                self._stats[path] = None
        return self._stats[path]

    def same_folder(self, first: Path, second: Path) -> bool:
        """Return whether two paths name the same existing directory."""
        if first == second:
            return True
        one, other = self._stat(first), self._stat(second)
        return (
            one is not None
            and other is not None
            and (one.st_dev, one.st_ino) == (other.st_dev, other.st_ino)
        )


def _first_existing(
    folder: Path, candidates: Sequence[str], listing: FolderListing
) -> Path | None:
    return next(
        (folder / name for name in candidates if listing.is_file(folder / name)),
        None,
    )


class AssetStorage:
    """Resolve, discover, and write managed local media assets."""

    def __init__(self, *, app_config: Settings) -> None:
        self._app_config = app_config
        self.asset_locks = KeyedLock[int | str]()

    def resolve_theme_path(self, folder_path: str) -> str:
        """Resolve the target path for a local theme audio file."""
        return str(Path(folder_path) / THEME_FILENAME)

    def resolve_art_path(
        self,
        folder_path: str,
        art_type: ArtType,
        ext: str = ".jpg",
        season_folder_path: str | None = None,
        season_num: int | None = None,
    ) -> str:
        """Resolve target file path based on art type and media-server naming rules."""
        if not art_type.owned_by_season:
            return str(Path(folder_path) / f"{art_type}{ext}")
        if season_num is None or season_num < 0:
            raise ValueError("A season poster requires a valid season number")
        dest_folder = self._resolve_season_folder(
            show_root=folder_path,
            season_num=season_num,
            season_folder_path=season_folder_path,
            listing=FolderListing(),
        )
        if dest_folder is None:
            raise TargetDirectoryMissingError(
                f"Season folder is not known for season {season_num}; "
                "sync the item after its season directory has been created."
            )
        return str(
            dest_folder
            / season_poster_filename(self._app_config.MEDIA_SERVER, season_num, ext)
        )

    def _resolve_season_folder(
        self,
        show_root: str | None,
        season_num: int | None,
        season_folder_path: str | None,
        *,
        listing: FolderListing,
    ) -> Path | None:
        """Resolve the same safe season location for reads and writes."""
        if season_folder_path:
            folder = Path(season_folder_path)
        else:
            if not show_root or season_num is None:
                return None
            probed = self.probe_season_folder(show_root, season_num, listing=listing)
            if not probed and not self._app_config.is_plex:
                return None
            folder = Path(probed or show_root)
        if (
            show_root
            and not self._app_config.is_plex
            and listing.same_folder(folder, Path(show_root))
        ):
            return None
        return folder

    def probe_season_folder(
        self,
        show_root: str,
        season_num: int,
        *,
        listing: FolderListing | None = None,
    ) -> str | None:
        """Try common Sonarr season subfolder names under show_root."""
        listing = listing or FolderListing()
        root = Path(show_root)
        if season_num == 0:
            candidates = ["Specials", "Season 00", "Season00"]
        else:
            candidates = [
                f"Season {season_num:02d}",
                f"Season{season_num:02d}",
                f"Season {season_num}",
            ]
        for name in candidates:
            p = root / name
            if listing.is_dir(p):
                return str(p)
        return None

    def find_local_art_path(
        self,
        art_type: ArtType,
        *,
        item: MediaItem,
        season: Season | None = None,
        listing: FolderListing | None = None,
    ) -> Path | None:
        """Return the local artwork path when a managed file exists.

        Pass one *listing* to every lookup of an inspection, so each folder is
        read once.
        """
        listing = listing or FolderListing()
        if art_type in ITEM_ART_TYPES:
            return self._find_item_art_path(art_type, item, listing)
        if art_type is ArtType.SEASON_POSTER and season is not None:
            return self._find_season_poster_path(item, season, listing)
        return None

    def local_theme_path(
        self, item: MediaItem, *, listing: FolderListing | None = None
    ) -> Path | None:
        """Return the local theme path for an item when it exists."""
        if not item or not item.folder_path:
            return None
        path = Path(item.folder_path) / THEME_FILENAME
        return path if (listing or FolderListing()).is_file(path) else None

    @staticmethod
    def _find_item_art_path(
        art_type: ArtType, item: MediaItem, listing: FolderListing
    ) -> Path | None:
        if not item or not item.folder_path:
            return None
        return _first_existing(
            Path(item.folder_path), ITEM_ASSET_CANDIDATES[art_type], listing
        )

    def _find_season_poster_path(
        self, item: MediaItem, season: Season, listing: FolderListing
    ) -> Path | None:
        folder = self._resolve_season_folder(
            item.folder_path, season.season_num, season.folder_path, listing=listing
        )
        if folder is None:
            return None
        candidates = season_poster_candidates(
            self._app_config.MEDIA_SERVER, season.season_num
        )
        if item.folder_path and listing.same_folder(folder, Path(item.folder_path)):
            # A root-level poster belongs to the show, never the season.
            candidates = [name for name in candidates if Path(name).stem != "poster"]
        return _first_existing(folder, candidates, listing)

    @staticmethod
    def _is_file(path: Path) -> bool:
        """Only confirmed absence is absence; propagate unavailable storage."""
        try:
            return stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError, NotADirectoryError:
            return False

    @staticmethod
    def _validated_target(
        target_path: str, trusted_root: str
    ) -> tuple[Path, Path, Path]:
        """Resolve a regular-file target beneath an existing trusted root."""
        try:
            root = Path(trusted_root).resolve(strict=True)
            parent = Path(target_path).parent.resolve(strict=True)
        except OSError as exc:
            raise TargetDirectoryMissingError(
                f"Target directory does not exist: {Path(target_path).parent!r}. "
                "Download the media first so the folder is created by your "
                "media manager."
            ) from exc

        target = parent / Path(target_path).name
        if not root.is_dir() or not parent.is_dir():
            raise TargetDirectoryMissingError(
                f"Target directory does not exist: {Path(target_path).parent!r}. "
                "Download the media first so the folder is created by your "
                "media manager."
            )
        if not target.is_relative_to(root):
            raise PathTraversalError(f"Path {target} escapes show root {root}")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise PathTraversalError(f"Asset target is not a regular file: {target}")
        return root, parent, target

    @staticmethod
    def _remove_alternate_images(target: Path) -> None:
        suffix = target.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            return
        for other in IMAGE_EXTENSIONS - {suffix}:
            target.with_suffix(other).unlink(missing_ok=True)

    def validate_target(self, target_path: str, trusted_root: str) -> None:
        """Validate a persisted replacement intent without changing the filesystem."""
        self._validated_target(target_path, trusted_root)

    def write_file(
        self, target_path: str, data: bytes, trusted_root: str
    ) -> StoredFile:
        """
        Atomically replace *target_path* beneath *trusted_root*.

        Raises:
            TargetDirectoryMissingError: When the target directory is missing.
            PathTraversalError: When the target escapes the trusted root.
            OSError: When the file cannot be written or committed.
        """
        root, parent, target = self._validated_target(target_path, trusted_root)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        temporary: Path | None = Path(temporary_name)
        try:
            temporary.chmod(0o644)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

            current = self._validated_target(target_path, trusted_root)
            if current != (root, parent, target):
                raise PathTraversalError(
                    "Asset target changed while it was being written"
                )

            temporary.replace(target)
            temporary = None
            sync_directory(parent)
        finally:
            if descriptor != -1:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        self._remove_alternate_images(target)
        sync_directory(parent)

        written = target.stat()
        stored = StoredFile(
            file_hash=compute_bytes_hash(data),
            mtime_ns=written.st_mtime_ns,
            size=written.st_size,
        )
        logger.debug(
            "Wrote %s (%d bytes, blake3 %s)",
            target,
            len(data),
            stored.file_hash[:12],
        )
        return stored

    async def write_file_async(
        self, target_path: str, data: bytes, trusted_root: str
    ) -> StoredFile:
        """Write an asset without blocking the event loop."""
        return await owned_thread(self.write_file, target_path, data, trusted_root)

    def stored_file(self, target_path: str | Path) -> StoredFile | None:
        """Return the file's hash and stat revision, or ``None`` when absent.

        Returns ``None`` too when the file changed while it was being hashed,
        so the caller never pairs a hash with another revision's stat.
        """
        path = Path(target_path)
        try:
            before = path.stat()
        except FileNotFoundError, NotADirectoryError:
            return None
        if not stat.S_ISREG(before.st_mode):
            return None
        file_hash = compute_file_hash(path)
        try:
            after = path.stat()
        except FileNotFoundError, NotADirectoryError:
            return None
        if file_hash is None or not same_revision(before, after):
            return None
        return StoredFile(file_hash, before.st_mtime_ns, before.st_size)

    def identical_file(self, target_path: str, file_hash: str) -> StoredFile | None:
        """Return the target when it already holds exactly these bytes.

        A target with a sibling image of another extension is not identical:
        writing it is what removes the sibling.
        """
        target = Path(target_path)
        if target.suffix.lower() in IMAGE_EXTENSIONS and any(
            self._is_file(target.with_suffix(other))
            for other in IMAGE_EXTENSIONS - {target.suffix.lower()}
        ):
            return None
        stored = self.stored_file(target)
        return stored if stored is not None and stored.file_hash == file_hash else None

    async def file_hash_async(self, target_path: str | Path) -> str | None:
        """Hash an asset without blocking the event loop."""
        return await owned_thread(compute_file_hash, target_path)
