"""Trusted media-root validation shared by route-facing services."""

lazy from pathlib import Path

lazy from ...db.session import Database
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.path import is_within_roots, real_path
lazy from ...utils.threads import owned_thread


def _resolve_roots(folder_paths: list[str]) -> list[str]:
    """Resolve each distinct item parent, and every symlinked item folder.

    An item folder that is not a symlink resolves inside its resolved parent,
    so it adds no root of its own; resolving only the few distinct parents
    keeps a large library from costing several stats per item.
    """
    item_folders = [Path(folder_path) for folder_path in folder_paths]
    roots = {real_path(parent) for parent in {folder.parent for folder in item_folders}}
    roots.update(real_path(folder) for folder in item_folders if folder.is_symlink())
    return sorted(roots)


async def trusted_media_roots(database: Database) -> list[str]:
    """Resolve filesystem roots after releasing the database connection."""
    async with database.read_session() as session:
        folder_paths = await MediaItemRepository(session).folder_paths()
    return await owned_thread(_resolve_roots, folder_paths)


async def require_trusted_media_roots(database: Database) -> list[str]:
    """Return trusted media roots or raise a public authorization error."""
    roots = await trusted_media_roots(database)
    if not roots:
        raise PublicServiceError(
            403,
            "No trusted media roots are available. Run a library sync first.",
        )
    return roots


def _first_invalid_folder(folders: list[str], allowed_roots: list[str]) -> str | None:
    """Check every folder in one worker-thread call."""
    return next(
        (
            folder
            for folder in folders
            if not Path(folder).is_dir() or not is_within_roots(folder, allowed_roots)
        ),
        None,
    )


async def validate_folders_under_trusted_roots(
    database: Database,
    folders: list[str],
) -> list[str]:
    """Validate that requested folders exist and stay inside trusted roots."""
    allowed_roots = await require_trusted_media_roots(database)
    invalid = await owned_thread(_first_invalid_folder, folders, allowed_roots)
    if invalid is not None:
        raise PublicServiceError(
            403,
            f"Invalid, untrusted, or non-existent folder: {invalid}",
        )
    return allowed_roots
