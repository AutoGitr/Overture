"""Inspect local theme files and record what they contain.

The file is read with no transaction open. Provenance embedded in the file
(a YouTube ID in its tags) becomes the item's selection only when the item
has none and the user has not cleared it.
"""

lazy import os
lazy from pathlib import Path

lazy from ...db.ledger import (
    FileFacts,
    local_file,
    read_asset,
    record_content,
    record_file,
    select_theme,
)
lazy from ...db.models.asset import Asset
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import Database
lazy from ...domain import ServerAsset
lazy from ...utils.audio import ThemeAudioMetadata, ffprobe_theme_metadata
lazy from ...utils.path import same_revision
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..storage.assets import AssetStorage, FolderListing


def _theme(item: MediaItem) -> Asset:
    return read_asset(item, ServerAsset.THEME)


def _selection(theme: Asset) -> tuple[object, ...]:
    """Return the selection columns a refresh may fill from the file's metadata."""
    return (
        theme.youtube_id,
        theme.youtube_id_source,
        theme.youtube_title,
        theme.youtube_duration,
        theme.provenance_cleared,
    )


def _wants_provenance(theme: Asset) -> bool:
    return not theme.provenance_cleared and (
        theme.youtube_id is None
        or theme.youtube_title is None
        or theme.youtube_duration is None
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
) -> tuple[FileFacts | None, ThemeAudioMetadata | None] | None:
    """Return the file's facts and tags, or ``None`` when it could not be read."""
    known = local_file(_theme(item))
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
    facts = FileFacts(
        file_hash=file_hash,
        # A failed probe leaves the revision unset so the next refresh retries.
        file_mtime_ns=stat.st_mtime_ns if metadata else None,
        file_size=stat.st_size if metadata else None,
        duration=round(metadata.duration) if metadata and metadata.duration else None,
    )
    return facts, metadata if _wants_provenance(_theme(item)) else None


def _adopt_provenance(
    item: MediaItem, facts: FileFacts | None, metadata: ThemeAudioMetadata | None
) -> None:
    """Fill a missing selection from the file's embedded YouTube ID.

    The file names the video it was made from, so it is that selection's
    content.
    """
    theme = _theme(item)
    if (
        facts is None
        or metadata is None
        or not metadata.youtube_id
        or metadata.youtube_id_source is None
        or theme.youtube_id not in {None, metadata.youtube_id}
    ):
        return
    adopted = theme.youtube_id is None
    select_theme(
        item,
        metadata.youtube_id,
        source=theme.youtube_id_source or metadata.youtube_id_source,
        title=theme.youtube_title or metadata.title,
        duration=theme.youtube_duration
        or (int(metadata.duration) if metadata.duration else None),
    )
    if adopted:
        record_content(item, ServerAsset.THEME, facts.content())


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
    before_file = local_file(_theme(item))
    before_selection = _selection(_theme(item))
    before_folder = item.folder_path

    inspection = await _inspect(item, asset_storage, listing)
    if inspection is None:
        return False
    facts, metadata = inspection
    if facts == before_file and metadata is None:
        return False

    async with database.write_session() as session:
        current = await session.get(MediaItem, item_id)
        # Do not overwrite a download, clear, move, or another refresh that
        # finished while the file was being inspected.
        if (
            current is None
            or current.folder_path != before_folder
            or local_file(_theme(current)) != before_file
            or _selection(_theme(current)) != before_selection
        ):
            return False
        record_file(current, ServerAsset.THEME, facts, at=utc_now())
        _adopt_provenance(current, facts, metadata)
        session.add(current)
        unmonitored = await auto_unmonitor_completed(session, current)
        return (
            unmonitored
            or facts != before_file
            or _selection(_theme(current)) != before_selection
        )
