"""Theme files in the folders Jellyfin keeps its collections in."""

lazy import stat
lazy from pathlib import Path

lazy from ...config import MediaServerConfig
lazy from ...db.theme_file import ThemeFileFacts
lazy from ...media_servers.adapters import server_path
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.hashing import compute_file_hash
lazy from ...utils.path import same_revision


def collection_folder(server: MediaServerConfig, collection_path: str | None) -> Path:
    """Return Overture's view of the folder *server* keeps a collection in.

    The folder is in the server's ``COLLECTIONS_PATH``; *collection_path* is
    the server's path of the collection. Only the folder's name is used: the
    server's own path means nothing inside Overture, and a single name cannot
    climb out of the collections path.

    Raises:
        ValueError: When no root is set, the name is unusable or no such
            folder is in *root*.
    """
    root = server.collections_path
    setting = server.variable("collections_path")
    if root is None:
        raise ValueError(f"Set {setting} to store collection themes")
    name = server_path(collection_path or "").name
    if name in {"", ".", ".."}:
        raise ValueError("The media server gave the collection no folder name")
    try:
        base = root.resolve(strict=True)
        folder = (base / name).resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"Collection folder {name!r} was not found in {setting}"
        ) from exc
    if folder.parent != base or not folder.is_dir():
        raise ValueError(f"Collection folder {name!r} is outside the collections path")
    # Jellyfin accepts either marker; XML saving can be disabled.
    if "[boxset]" not in name.casefold() and not (folder / "collection.xml").is_file():
        raise ValueError(f"Collection folder {name!r} has no BoxSet marker")
    return folder


def inspect_theme_file(
    folder: Path, known: ThemeFileFacts | None = None
) -> ThemeFileFacts | None:
    """Read stable file facts, reusing the hash of an unchanged revision."""
    path = folder / THEME_FILENAME
    if path.resolve().parent != folder:
        raise ValueError("Collection theme is outside its folder")
    try:
        before = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Collection theme is not a regular file")
    if (
        known
        and known.file_size == before.st_size
        and known.file_mtime_ns == before.st_mtime_ns
    ):
        return known
    file_hash = compute_file_hash(path)
    if file_hash is None or not same_revision(before, path.stat()):
        raise ValueError("Collection theme changed while it was inspected")
    return ThemeFileFacts(
        file_hash,
        before.st_mtime_ns,
        before.st_size,
        known.duration if known and known.file_hash == file_hash else None,
    )
