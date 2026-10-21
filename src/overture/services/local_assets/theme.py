"""Inspect local theme files and record what they contain.

The file is read with no transaction open. Provenance embedded in the file
(a YouTube ID in its tags) becomes the item's selection only when the item
has none and the user has not cleared it.
"""

lazy import os
lazy from pathlib import Path

lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import Database
lazy from ...db.theme_file import (
    ThemeFileFacts,
    record_theme_file,
    select_theme,
    theme_file_columns,
    theme_file_facts,
)
lazy from ...utils.audio import ThemeAudioMetadata, ffprobe_theme_metadata
lazy from ...utils.path import same_revision
lazy from ...utils.threads import owned_thread
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..storage.assets import AssetStorage, FolderListing


def _selection(item: MediaItem) -> tuple[object, ...]:
    """Return the selection columns a refresh may fill from the file's metadata."""
    return (
        item.youtube_id,
        item.youtube_id_source,
        item.youtube_title,
        item.youtube_duration,
    )


def _wants_provenance(item: MediaItem) -> bool:
    return not item.theme_provenance_cleared and (
        item.youtube_id is None
        or item.youtube_title is None
        or item.youtube_duration is None
    )


def _locate(
    item: MediaItem, asset_storage: AssetStorage, listing: FolderListing
) -> tuple[Path, os.stat_result] | None:
    """Find and stat the item's theme file in one worker-thread call.

    Raises:
        OSError: The file is there but could not be stat'ed.
    """
    path = asset_storage.local_theme_path(item, listing=listing)
    return None if path is None else (path, path.stat())


async def _inspect(
    item: MediaItem, asset_storage: AssetStorage, listing: FolderListing
) -> tuple[ThemeFileFacts | None, ThemeAudioMetadata | None] | None:
    """Return the file's facts and tags, or ``None`` when it could not be read."""
    known = theme_file_facts(item)
    try:
        located = await owned_thread(_locate, item, asset_storage, listing)
        if located is None:
            return None, None
        path, stat = located
        if (
            known is not None
            and known.file_mtime_ns == stat.st_mtime_ns
            and known.file_size == stat.st_size
        ):
            return known, None
        file_hash = await asset_storage.file_hash_async(path)
        if file_hash is None:
            return None
        metadata = await ffprobe_theme_metadata(path)
        after = await owned_thread(path.stat)
    except OSError:
        return None
    if not same_revision(stat, after):
        return None
    facts = ThemeFileFacts(
        file_hash=file_hash,
        # A failed probe leaves the revision unset so the next refresh retries.
        file_mtime_ns=stat.st_mtime_ns if metadata else None,
        file_size=stat.st_size if metadata else None,
        duration=round(metadata.duration) if metadata and metadata.duration else None,
    )
    return facts, metadata if _wants_provenance(item) else None


def _adopt_provenance(item: MediaItem, metadata: ThemeAudioMetadata | None) -> None:
    """Fill a missing selection from the file's embedded YouTube ID."""
    if (
        metadata is None
        or not metadata.youtube_id
        or metadata.youtube_id_source is None
        or item.youtube_id not in {None, metadata.youtube_id}
    ):
        return
    select_theme(
        item,
        metadata.youtube_id,
        source=item.youtube_id_source or metadata.youtube_id_source,
        title=item.youtube_title or metadata.title,
        duration=item.youtube_duration
        or (int(metadata.duration) if metadata.duration else None),
    )


async def refresh_theme(
    item: MediaItem,
    asset_storage: AssetStorage,
    database: Database,
    *,
    listing: FolderListing,
) -> bool:
    """Record the item's current theme file; return whether the record changed.

    *item* is the row as read before the file is.
    """
    if item.id is None:
        return False
    item_id = item.id
    before_columns = theme_file_columns(item)
    before_selection = _selection(item)
    before_folder = item.folder_path
    before_cleared = item.theme_provenance_cleared

    inspection = await _inspect(item, asset_storage, listing)
    if inspection is None:
        return False
    facts, metadata = inspection
    if theme_file_columns(facts) == before_columns and metadata is None:
        return False

    async with database.write_session() as session:
        current = await session.get(MediaItem, item_id)
        # Do not overwrite a download, clear, move, or another refresh that
        # finished while the file was being inspected.
        if (
            current is None
            or current.folder_path != before_folder
            or current.theme_provenance_cleared != before_cleared
            or theme_file_columns(current) != before_columns
            or _selection(current) != before_selection
        ):
            return False
        record_theme_file(current, facts)
        _adopt_provenance(current, metadata)
        session.add(current)
        unmonitored = await auto_unmonitor_completed(session, current)
        return (
            unmonitored
            or theme_file_columns(facts) != before_columns
            or _selection(current) != before_selection
        )
