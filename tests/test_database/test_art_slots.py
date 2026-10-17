"""The single read/write surface for normalised artwork slots.

Artwork lives in ``media_item_art`` and ``season_art``, one row per owner and
art type, so ``art_type`` selects a row instead of a column-name prefix.
"""

lazy import pytest

lazy from overture.db.art_slots import (
    ART_SLOT_FIELDS,
    ArtFileFacts,
    art_file_facts,
    art_slot,
    clear_art_selection,
    find_art_slot,
    read_art_slot,
    record_art_file,
    select_art,
    write_art_slot,
)
lazy from overture.db.models.art import ArtSlot
lazy from overture.domain import ITEM_ART_TYPES, ArtType
lazy from tests.factories import (
    MediaItemFactory,
    SeasonFactory,
)


def test_item_art_types_are_the_ones_owned_by_a_media_item() -> None:
    assert set(ITEM_ART_TYPES) == {ArtType.POSTER, ArtType.BACKGROUND}
    assert ArtType.SEASON_POSTER.owned_by_season is True
    assert ArtType.POSTER.owned_by_season is False


def test_reading_an_absent_slot_returns_an_empty_detached_slot(
    media_item_factory: MediaItemFactory,
) -> None:
    """Reads must never attach a row; an item with no art has no art rows."""
    item = media_item_factory(id=1)

    slot = read_art_slot(item, ArtType.POSTER)

    assert slot.url is None
    assert slot.art_type is ArtType.POSTER
    assert item.art_slots == []
    assert find_art_slot(item, ArtType.POSTER) is None


def test_writing_creates_exactly_one_slot_and_reuses_it(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)

    write_art_slot(item, ArtType.POSTER, url="https://cdn.test/a.jpg")
    write_art_slot(item, ArtType.POSTER, url="https://cdn.test/b.jpg", width=600)

    assert len(item.art_slots) == 1
    slot = read_art_slot(item, ArtType.POSTER)
    assert slot.url == "https://cdn.test/b.jpg"
    assert slot.width == 600


def test_slots_of_different_types_do_not_collide(
    media_item_factory: MediaItemFactory,
) -> None:
    """The bug the parallel columns existed to avoid, now enforced by the key."""
    item = media_item_factory(id=1)

    write_art_slot(item, ArtType.POSTER, url="https://cdn.test/p.jpg", width=600)
    write_art_slot(item, ArtType.BACKGROUND, url="https://cdn.test/b.jpg", width=1920)

    assert read_art_slot(item, ArtType.POSTER).url == "https://cdn.test/p.jpg"
    assert read_art_slot(item, ArtType.POSTER).width == 600
    assert read_art_slot(item, ArtType.BACKGROUND).url == "https://cdn.test/b.jpg"
    assert read_art_slot(item, ArtType.BACKGROUND).width == 1920


def test_write_rejects_a_field_the_slot_does_not_have(
    media_item_factory: MediaItemFactory,
) -> None:
    """Guards against a caller inventing a field that would be dropped."""
    item = media_item_factory(id=1)

    with pytest.raises(ValueError, match="Unknown art slot fields"):
        write_art_slot(item, ArtType.POSTER, poster_url="https://cdn.test/p.jpg")

    assert item.art_slots == []


def test_write_can_set_every_declared_slot_field(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)

    write_art_slot(
        item,
        ArtType.POSTER,
        url="https://cdn.test/p.jpg",
        file_hash="h",
        phash="ph",
        width=600,
        height=900,
        file_mtime_ns=99,
        file_size=1024,
    )

    slot = read_art_slot(item, ArtType.POSTER)
    assert all(getattr(slot, field) is not None for field in ART_SLOT_FIELDS)


def _facts(file_hash: str = "h") -> ArtFileFacts:
    return ArtFileFacts(
        file_hash=file_hash,
        phash="0" * 16,
        width=1000,
        height=1500,
        file_mtime_ns=1,
        file_size=10,
    )


def test_local_file_record_lives_on_the_slot(
    media_item_factory: MediaItemFactory,
) -> None:
    """A recorded file belongs to the artwork it describes, not to the owner."""
    item = media_item_factory(id=1)

    record_art_file(item, ArtType.POSTER, _facts())

    assert read_art_slot(item, ArtType.POSTER).file_hash == "h"
    assert read_art_slot(item, ArtType.BACKGROUND).file_hash is None


def test_saving_a_selection_leaves_the_file_record_alone(
    media_item_factory: MediaItemFactory,
) -> None:
    """Saving a new selection must neither claim nor forget a local file."""
    item = media_item_factory(id=1, art={"poster": {"file_hash": "h"}})

    select_art(item, ArtType.POSTER, "https://cdn.test/p.jpg")

    assert read_art_slot(item, ArtType.POSTER).file_hash == "h"


def test_clearing_a_selection_keeps_the_local_file_record(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)
    select_art(item, ArtType.POSTER, "https://cdn.test/p.jpg")
    record_art_file(item, ArtType.POSTER, _facts())

    clear_art_selection(item, ArtType.POSTER)

    slot = read_art_slot(item, ArtType.POSTER)
    assert slot.url is None
    assert art_file_facts(slot) == _facts()


def test_clearing_a_selection_without_a_file_drops_the_row(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)
    select_art(item, ArtType.POSTER, "https://cdn.test/p.jpg")

    clear_art_selection(item, ArtType.POSTER)

    assert item.art_slots == []


def test_forgetting_a_file_clears_every_file_fact_but_keeps_the_selection(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)
    select_art(item, ArtType.POSTER, "https://cdn.test/p.jpg")
    record_art_file(item, ArtType.POSTER, _facts())

    record_art_file(item, ArtType.POSTER, None)

    slot = read_art_slot(item, ArtType.POSTER)
    assert slot.url == "https://cdn.test/p.jpg"
    assert (
        slot.file_hash,
        slot.phash,
        slot.width,
        slot.height,
        slot.file_mtime_ns,
        slot.file_size,
    ) == (None, None, None, None, None, None)


def test_forgetting_the_only_fact_of_a_slot_drops_the_row(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)
    record_art_file(item, ArtType.POSTER, _facts())

    record_art_file(item, ArtType.POSTER, None)

    assert item.art_slots == []


def test_recording_one_slot_leaves_the_others_untouched(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=1)
    select_art(item, ArtType.BACKGROUND, "https://cdn.test/b.jpg")

    record_art_file(item, ArtType.POSTER, _facts())

    assert read_art_slot(item, ArtType.BACKGROUND).url == "https://cdn.test/b.jpg"
    assert read_art_slot(item, ArtType.BACKGROUND).file_hash is None
    assert art_file_facts(read_art_slot(item, ArtType.POSTER)) == _facts()


def test_season_posters_are_owned_by_the_season(season_factory: SeasonFactory) -> None:
    season = season_factory(id=10)

    write_art_slot(
        season,
        ArtType.SEASON_POSTER,
        url="https://cdn.test/s.jpg",
        file_hash="s",
    )

    slot = art_slot(season, ArtType.SEASON_POSTER)
    assert isinstance(slot, ArtSlot)
    assert slot.season_id == 10
    assert slot.file_hash == "s"


def test_slot_records_the_owner_identity_it_was_created_for(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=7)

    slot = art_slot(item, ArtType.BACKGROUND)

    assert isinstance(slot, ArtSlot)
    assert (slot.media_item_id, slot.art_type) == (7, ArtType.BACKGROUND)
