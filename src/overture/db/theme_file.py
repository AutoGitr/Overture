"""Single write surface for an item's theme selection and local theme file.

A media item carries two kinds of theme state: the selection (which YouTube
video the theme is, and how that was established) and the facts about the
local ``theme.mp3`` (its hash, present only while a file is recorded, and the
stat revision it was inspected at). Each kind is written only here, as a
whole, so the columns of one kind can never describe different things.
"""

lazy from dataclasses import dataclass

lazy from ..domain import ThemeIdSource
lazy from .models.media_item import MediaItem


@dataclass(frozen=True, slots=True)
class ThemeFileFacts:
    """What one inspection of a local theme file established.

    ``file_mtime_ns``/``file_size`` are ``None`` when the file's metadata could
    not be read, so the next inspection tries again even if the audio is
    unchanged.
    """

    file_hash: str
    file_mtime_ns: int | None
    file_size: int | None


def theme_file_facts(item: MediaItem) -> ThemeFileFacts | None:
    """Return the recorded facts of the item's local theme file, or ``None``."""
    if item.theme_file_hash is None:
        return None
    return ThemeFileFacts(
        file_hash=item.theme_file_hash,
        file_mtime_ns=item.theme_file_mtime_ns,
        file_size=item.theme_file_size,
    )


def theme_file_columns(
    item: MediaItem | ThemeFileFacts | None,
) -> tuple[str | None, int | None, int | None]:
    """Return the theme file columns an item holds, or would hold for *facts*.

    Comparing these also catches columns that disagree with each other.
    """
    if item is None:
        return (None, None, None)
    if isinstance(item, ThemeFileFacts):
        return (item.file_hash, item.file_mtime_ns, item.file_size)
    return (
        item.theme_file_hash,
        item.theme_file_mtime_ns,
        item.theme_file_size,
    )


def record_theme_file(item: MediaItem, facts: ThemeFileFacts | None) -> None:
    """Record the item's local theme file, or its absence."""
    item.theme_file_hash = facts.file_hash if facts else None
    item.theme_file_mtime_ns = facts.file_mtime_ns if facts else None
    item.theme_file_size = facts.file_size if facts else None


def select_theme(
    item: MediaItem,
    youtube_id: str,
    *,
    source: ThemeIdSource,
    title: str | None,
    duration: int | None,
) -> None:
    """Record *youtube_id* as the item's theme and how it was established."""
    item.youtube_id = youtube_id
    item.youtube_id_source = source
    item.youtube_title = title
    item.youtube_duration = duration
    item.theme_provenance_cleared = False


def clear_theme_selection(item: MediaItem) -> None:
    """Forget the item's theme selection; the local file and its facts remain.

    Provenance stays cleared until a new selection is recorded, so a later
    inspection does not read the old video ID back from the file's metadata.
    """
    item.youtube_id = None
    item.youtube_id_source = None
    item.youtube_title = None
    item.youtube_duration = None
    item.theme_provenance_cleared = True
