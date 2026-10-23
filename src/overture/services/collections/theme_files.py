"""Theme files in the folders Jellyfin keeps its collections in."""

lazy import stat
lazy from pathlib import Path

lazy from ...db.theme_file import ThemeFileFacts
lazy from ...media_servers.adapters import server_path
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.file import compute_file_hash
lazy from ...utils.path import same_revision


def collection_folder(root: Path, collection_path: str) -> Path:
    """Return Overture's view of the folder the server keeps a collection in.

    Only the folder's name is used: the server's own path means nothing inside
    Overture, and a single name cannot climb out of *root*.

    Raises:
        ValueError: When the name is unusable or no such folder is in *root*.
    """
    name = server_path(collection_path).name
    if name in {"", ".", ".."}:
        raise ValueError("The media server gave the collection no folder name")
    try:
        base = root.resolve(strict=True)
        folder = (base / name).resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"Collection folder {name!r} was not found in JELLYFIN_COLLECTIONS_PATH"
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
