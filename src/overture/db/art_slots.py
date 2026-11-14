"""Single read/write surface for artwork slots.

Items, seasons and collections expose artwork through ``art_slots``, so every
helper works the same way for all owners. Callers
name the slot they want with an :class:`~overture.domain.ArtType`; nothing
outside this module builds slot rows by hand.
"""

lazy from dataclasses import asdict, dataclass, fields
lazy from functools import cache
lazy from operator import attrgetter

lazy from ..domain import ArtGeneration, ArtSource, ArtType
lazy from ..utils.art_urls import PublicArtUrl, selected_art_source
lazy from .models.art import ArtSlot
lazy from .models.media_collection import MediaCollection
lazy from .models.media_item import MediaItem
lazy from .models.season import Season


def _slots(owner: MediaItem | Season | MediaCollection) -> list[ArtSlot]:
    """Return the owner's slot rows."""
    return owner.art_slots


def _empty_slot(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType
) -> ArtSlot:
    """Return an unattached slot row of the right type for *owner*."""
    if isinstance(owner, MediaCollection):
        return ArtSlot(collection_id=owner.id, art_type=art_type)
    if isinstance(owner, Season):
        return ArtSlot(season_id=owner.id, art_type=art_type)
    return ArtSlot(media_item_id=owner.id, art_type=art_type)


@cache
def _blank_slot(art_type: ArtType) -> ArtSlot:
    """A slot holding nothing: a library list reads one per title lacking art."""
    return ArtSlot(art_type=art_type)


def find_art_slot(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType
) -> ArtSlot | None:
    """Return the stored slot for *art_type*, or ``None`` when absent."""
    for slot in _slots(owner):
        if slot.art_type == art_type:
            return slot
    return None


def art_slot(owner: MediaItem | Season | MediaCollection, art_type: ArtType) -> ArtSlot:
    """Return the slot for *art_type*, creating an empty one when absent.

    The new row is attached to the owner's collection, so the ORM inserts it
    with the rest of the unit of work; nothing is written until a flush.
    """
    existing = find_art_slot(owner, art_type)
    if existing is not None:
        return existing
    created = _empty_slot(owner, art_type)
    _slots(owner).append(created)
    return created


def read_art_slot(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType
) -> ArtSlot:
    """Return the slot for *art_type* without attaching a row to the session.

    Use this on read paths; it hands back a shared, empty slot when the owner
    has never had artwork of that type, which must not be written to.
    """
    return find_art_slot(owner, art_type) or _blank_slot(art_type)


def _write_art_slot(
    owner: MediaItem | Season | MediaCollection,
    art_type: ArtType,
    **fields: object,
) -> ArtSlot:
    """Write file facts, creating the slot when the owner has none.

    ``select_art`` alone writes the link.
    """
    slot = art_slot(owner, art_type)
    for name, value in fields.items():
        setattr(slot, name, value)
    return slot


@dataclass(frozen=True, slots=True)
class ArtFileFacts:
    """What one inspection of a local artwork file established.

    A slot's file columns are only ever written from one of these, together,
    so the hash, fingerprint, dimensions and stat revision always describe the
    same bytes. Nothing else writes them.
    """

    file_hash: str
    phash: str | None
    width: int | None
    height: int | None
    file_mtime_ns: int
    file_size: int


#: The slot columns that describe its local file, named as the facts name them.
_FILE_FIELDS = tuple(field.name for field in fields(ArtFileFacts))
_file_columns = attrgetter(*_FILE_FIELDS)


def art_file_facts(slot: ArtSlot) -> ArtFileFacts | None:
    """Return the recorded facts of the slot's local file, or ``None``."""
    if slot.file_hash is None or slot.file_mtime_ns is None or slot.file_size is None:
        return None
    return ArtFileFacts(*_file_columns(slot))


type ArtFileColumns = tuple[
    str | None, str | None, int | None, int | None, int | None, int | None
]


def art_file_columns(slot: ArtSlot | ArtFileFacts | None) -> ArtFileColumns:
    """Return the file columns a slot holds, or would hold for *facts*.

    Comparing these rather than :func:`art_file_facts` also catches a row whose
    columns disagree with each other, so a refresh repairs it.
    """
    if slot is None:
        return (None, None, None, None, None, None)
    return _file_columns(slot)


def record_selected_art_file(
    owner: MediaItem | Season | MediaCollection,
    art_type: ArtType,
    facts: ArtFileFacts,
) -> None:
    """Record the slot's local file as the one holding its selection."""
    _write_art_slot(owner, art_type, selection_hash=facts.file_hash, **asdict(facts))


def file_holds_selection(slot: ArtSlot) -> bool:
    """Return whether the slot's recorded file holds its selection.

    A file recorded before Overture wrote or verified one for the selection
    is taken to hold it.
    """
    return art_file_facts(slot) is not None and slot.selection_hash in {
        None,
        slot.file_hash,
    }


def record_art_file(
    owner: MediaItem | Season | MediaCollection,
    art_type: ArtType,
    facts: ArtFileFacts | None,
) -> ArtSlot | None:
    """Record the slot's local file, or its absence when *facts* is ``None``.

    Returns:
        The written slot, or ``None`` when an absent file left nothing to keep.
    """
    if facts is not None:
        return _write_art_slot(owner, art_type, **asdict(facts))
    slot = find_art_slot(owner, art_type)
    if slot is None:
        return None
    _write_art_slot(owner, art_type, **dict.fromkeys(_FILE_FIELDS))
    _drop_if_empty(owner, slot)
    return None


@dataclass(frozen=True, slots=True)
class SavedArt:
    """A slot's selection: a public link, or the hash of an uploaded image."""

    url: PublicArtUrl | None = None
    upload_hash: str | None = None


def saved_art(slot: ArtSlot | None) -> SavedArt | None:
    """Return what the slot selects, or ``None`` when it selects nothing."""
    if slot is None or (slot.url is None and slot.upload_hash is None):
        return None
    return SavedArt(slot.url, slot.upload_hash)


def slot_art_source(slot: ArtSlot) -> ArtSource | None:
    """Return where the slot's selected artwork comes from, if it selects any."""
    if slot.generated_style:
        return ArtSource.GENERATED
    return ArtSource.UPLOAD if slot.upload_hash else selected_art_source(slot.url)


#: The slot columns responses show, by the name after their prefix.
_FLATTENED_COLUMNS = {
    "url": attrgetter("url"),
    "hash": attrgetter("file_hash"),
    "phash": attrgetter("phash"),
    "width": attrgetter("width"),
    "height": attrgetter("height"),
    "source": slot_art_source,
}


def flattened_art(slot: ArtSlot, prefix: str) -> dict[str, object]:
    """Return the slot as the ``<prefix>_*`` fields responses carry."""
    return {f"{prefix}_{name}": read(slot) for name, read in _FLATTENED_COLUMNS.items()}


def flattened_art_names(prefix: str) -> set[str]:
    """Return the names of the fields ``flattened_art`` gives under *prefix*."""
    return {f"{prefix}_{name}" for name in _FLATTENED_COLUMNS}


def select_art(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType, url: PublicArtUrl
) -> ArtSlot:
    """Record *url* as the slot's selected artwork, leaving file facts alone."""
    slot = art_slot(owner, art_type)
    if (slot.url, slot.upload_hash) != (url, None):
        slot.selection_hash = None
    slot.url = url
    slot.upload_hash = None
    slot.generated_style = None
    slot.generated_title_only = False
    return slot


def select_upload(
    owner: MediaItem | Season | MediaCollection,
    art_type: ArtType,
    upload_hash: str,
    *,
    generated: ArtGeneration | None = None,
) -> ArtSlot:
    """Record the kept image *upload_hash* as the slot's selected artwork.

    *generated* says how Overture drew it, for an image it made.
    """
    slot = art_slot(owner, art_type)
    if (slot.url, slot.upload_hash) != (None, upload_hash):
        slot.selection_hash = None
    slot.url = None
    slot.upload_hash = upload_hash
    slot.generated_style = generated.style if generated else None
    slot.generated_title_only = generated.title_only if generated else False
    return slot


def art_generation(slot: ArtSlot) -> ArtGeneration | None:
    """Return how Overture drew the slot's art, if it drew it."""
    if slot.generated_style is None:
        return None
    return ArtGeneration(slot.generated_style, title_only=slot.generated_title_only)


def clear_art_selection(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType
) -> None:
    """Forget the slot's selection; facts about a local file are kept."""
    slot = find_art_slot(owner, art_type)
    if slot is None:
        return
    slot.url = None
    slot.upload_hash = None
    slot.selection_hash = None
    slot.generated_style = None
    slot.generated_title_only = False
    _drop_if_empty(owner, slot)


def _drop_if_empty(owner: MediaItem | Season | MediaCollection, slot: ArtSlot) -> None:
    """Delete a row that no longer records a selection or a local file."""
    if saved_art(slot) is None and slot.file_hash is None:
        _slots(owner).remove(slot)
