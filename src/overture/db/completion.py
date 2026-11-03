"""The one definition of when an asset is complete.

A slot or theme is complete once Overture records both the selection (the
artwork link or YouTube ID) and a local file (its hash). An item without a
local folder can hold no files, so its selection alone completes it. Every
consumer - the library API, auto-unmonitor and the statistics - applies these
rules, either to loaded rows or, for aggregate queries, as the SQL clauses
below.
"""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass

lazy from sqlmodel import and_, col, or_

lazy from ..domain import ArtType, AssetStatus, MediaType
lazy from .art_slots import find_art_slot
lazy from .models.art import ArtSlot
lazy from .models.media_collection import MediaCollection
lazy from .models.media_item import MediaItem
lazy from .models.season import Season

#: SQL form of :func:`holds_files`.
HOLDS_FILES = col(MediaItem.folder_path).is_not(None)

#: SQL form of :func:`slot_complete`; the query must join the owning
#: :class:`MediaItem`.
SLOT_COMPLETE = and_(
    col(ArtSlot.url).is_not(None),
    or_(col(ArtSlot.file_hash).is_not(None), ~HOLDS_FILES),
)

#: SQL form of a complete item theme.
THEME_COMPLETE = and_(
    col(MediaItem.youtube_id).is_not(None),
    or_(col(MediaItem.theme_file_hash).is_not(None), ~HOLDS_FILES),
)


def holds_files(item: MediaItem) -> bool:
    """Return whether the item has a local folder its assets are written to."""
    return item.folder_path is not None


def _status(*, complete: bool, started: bool) -> AssetStatus:
    if complete:
        return AssetStatus.COMPLETE
    return AssetStatus.PARTIAL if started else AssetStatus.MISSING


def slot_complete(slot: ArtSlot | None, *, files: bool) -> bool:
    """Return whether a slot records its artwork link and, when *files*, a file."""
    return (
        slot is not None
        and slot.url is not None
        and (slot.file_hash is not None or not files)
    )


def _slot_started(slot: ArtSlot | None) -> bool:
    return slot is not None and (slot.url is not None or slot.file_hash is not None)


def slot_status(slot: ArtSlot | None, *, files: bool) -> AssetStatus:
    """Return how much of one artwork slot is recorded."""
    return _status(
        complete=slot_complete(slot, files=files), started=_slot_started(slot)
    )


@dataclass(frozen=True, slots=True)
class ArtCompletion:
    """Artwork completeness of one media item, per slot and overall."""

    poster_status: AssetStatus
    background_status: AssetStatus
    season_posters_status: AssetStatus
    art_status: AssetStatus


def art_completion(item: MediaItem, seasons: Sequence[Season]) -> ArtCompletion:
    """Summarise an item's artwork; *seasons* are its tracked seasons.

    A show is complete only with a complete poster for every such season, so a
    show without any tracked season never is.
    """
    files = holds_files(item)
    show = item.media_type == MediaType.SHOW
    season_posters = (
        [find_art_slot(season, ArtType.SEASON_POSTER) for season in seasons]
        if show
        else []
    )
    poster_status = slot_status(find_art_slot(item, ArtType.POSTER), files=files)
    background_status = slot_status(
        find_art_slot(item, ArtType.BACKGROUND), files=files
    )
    season_posters_status = _status(
        complete=bool(season_posters)
        and all(slot_complete(slot, files=files) for slot in season_posters),
        started=any(_slot_started(slot) for slot in season_posters),
    )
    parts = (
        poster_status,
        background_status,
        *((season_posters_status,) if show else ()),
    )
    return ArtCompletion(
        poster_status=poster_status,
        background_status=background_status,
        season_posters_status=season_posters_status,
        art_status=_status(
            complete=all(part == "complete" for part in parts),
            started=any(part is not AssetStatus.MISSING for part in parts),
        ),
    )


def collection_art_completion(collection: MediaCollection) -> ArtCompletion:
    """Summarise selected collection art and the copies held by its server."""

    def status(art_type: ArtType, server_url: str | None) -> AssetStatus:
        slot = find_art_slot(collection, art_type)
        return _status(
            complete=slot_complete(slot, files=True),
            started=_slot_started(slot) or server_url is not None,
        )

    poster = status(ArtType.POSTER, collection.thumb_url)
    background = status(ArtType.BACKGROUND, collection.art_url)
    return ArtCompletion(
        poster_status=poster,
        background_status=background,
        season_posters_status=AssetStatus.MISSING,
        art_status=_status(
            complete=poster is AssetStatus.COMPLETE
            and background is AssetStatus.COMPLETE,
            started=poster is not AssetStatus.MISSING
            or background is not AssetStatus.MISSING,
        ),
    )


def theme_status(item: MediaItem) -> AssetStatus:
    """Return how much of an item's theme is recorded."""
    selected = item.youtube_id is not None
    local = item.theme_file_hash is not None
    return _status(
        complete=selected and (local or not holds_files(item)),
        started=selected or local,
    )


def collection_theme_status(
    *, server_has_theme: bool, youtube_id: str | None
) -> AssetStatus:
    """Return a collection theme's status.

    The media server holds a collection's theme, so its presence there takes
    the place of a local file.
    """
    selected = youtube_id is not None
    return _status(
        complete=selected and server_has_theme, started=selected or server_has_theme
    )
