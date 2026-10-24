"""Single read/write surface for artwork slots.

Items, seasons and collections expose artwork through ``art_slots``, so every
helper works the same way for all owners. Callers
name the slot they want with an :class:`~overture.domain.ArtType`; nothing
outside this module builds slot rows by hand.
"""

lazy from dataclasses import asdict, dataclass, fields
lazy from operator import attrgetter

lazy from ..domain import ArtType
lazy from .models.art import ART_SLOT_FIELDS, ArtSlot
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

    Use this on read paths; it hands back a detached, empty slot when the
    owner has never had artwork of that type.
    """
    return find_art_slot(owner, art_type) or _empty_slot(owner, art_type)


def write_art_slot(
    owner: MediaItem | Season | MediaCollection,
    art_type: ArtType,
    **fields: object,
) -> ArtSlot:
    """Write slot fields, creating the slot when the owner has none.

    Returns:
        The slot that was written.

    Raises:
        ValueError: When a field name is not an art slot field.
    """
    unknown = set(fields) - set(ART_SLOT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown art slot fields: {sorted(unknown)}")
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
        return write_art_slot(owner, art_type, **asdict(facts))
    slot = find_art_slot(owner, art_type)
    if slot is None:
        return None
    write_art_slot(owner, art_type, **dict.fromkeys(_FILE_FIELDS))
    _drop_if_empty(owner, slot)
    return None


def select_art(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType, url: str
) -> ArtSlot:
    """Record *url* as the slot's selected artwork, leaving file facts alone."""
    return write_art_slot(owner, art_type, url=url)


def clear_art_selection(
    owner: MediaItem | Season | MediaCollection, art_type: ArtType
) -> None:
    """Forget the slot's selected URL; facts about a local file are kept."""
    slot = find_art_slot(owner, art_type)
    if slot is None:
        return
    slot.url = None
    _drop_if_empty(owner, slot)


def _drop_if_empty(owner: MediaItem | Season | MediaCollection, slot: ArtSlot) -> None:
    """Delete a row that no longer records a selection or a local file."""
    if slot.url is None and slot.file_hash is None:
        _slots(owner).remove(slot)
