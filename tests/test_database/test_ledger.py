"""The ledger: one rule decides every asset's status, and only it writes assets."""

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.ledger import (
    ContentFacts,
    Destination,
    Evidence,
    FileFacts,
    clear_selection,
    combined_status,
    confirm_delivery,
    generation,
    item_art_status,
    local_file,
    observe,
    place,
    place_local,
    read_asset,
    record_content,
    record_file,
    record_written,
    select_art,
    select_theme,
    select_upload,
    set_needed,
    settled_status,
)
lazy from overture.db.models.asset import Asset, AssetDelivery
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.domain import (
    ArtGeneration,
    ArtStyle,
    AssetStatus,
    DeliveryChannel,
    MediaType,
    ServerAsset,
    ThemeIdSource,
)
lazy from overture.utils.art_urls import PublicArtUrl

URL = PublicArtUrl("https://image.tmdb.org/t/p/original/a.jpg")
OTHER = PublicArtUrl("https://image.tmdb.org/t/p/original/b.jpg")
COPY = Destination(1, "box", DeliveryChannel.UPLOAD)


def _file(file_hash: str = "file") -> FileFacts:
    return FileFacts(file_hash, 1, 2, "0" * 64, 1000, 1500)


def _item(*, folder: bool = True) -> MediaItem:
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Alien",
        folder_path="/m" if folder else None,
    )
    place_local(item, (ServerAsset.POSTER,), folder=folder)
    return item


def _status(owner: MediaItem | MediaCollection, kind: ServerAsset) -> AssetStatus:
    return read_asset(owner, kind).status


def test_an_asset_in_a_folder_is_complete_once_the_file_holds_its_selection() -> None:
    item = _item()
    assert _status(item, ServerAsset.POSTER) is AssetStatus.MISSING

    select_art(item, ServerAsset.POSTER, URL)
    assert _status(item, ServerAsset.POSTER) is AssetStatus.PARTIAL

    record_written(item, ServerAsset.POSTER, _file())
    assert _status(item, ServerAsset.POSTER) is AssetStatus.COMPLETE


def test_a_file_replaced_outside_overture_no_longer_completes_its_asset() -> None:
    item = _item()
    select_art(item, ServerAsset.POSTER, URL)
    record_written(item, ServerAsset.POSTER, _file("written"))

    record_file(item, ServerAsset.POSTER, _file("replaced"))

    assert _status(item, ServerAsset.POSTER) is AssetStatus.PARTIAL
    assert local_file(read_asset(item, ServerAsset.POSTER)) == _file("replaced")


def test_a_new_selection_is_not_completed_by_the_previous_ones_file() -> None:
    item = _item()
    select_art(item, ServerAsset.POSTER, URL)
    record_written(item, ServerAsset.POSTER, _file())

    select_art(item, ServerAsset.POSTER, OTHER)

    assert _status(item, ServerAsset.POSTER) is AssetStatus.PARTIAL


def test_without_a_folder_the_selection_alone_completes_an_asset() -> None:
    item = _item(folder=False)

    select_art(item, ServerAsset.POSTER, URL)

    assert _status(item, ServerAsset.POSTER) is AssetStatus.COMPLETE


def test_clearing_a_selection_keeps_the_file_seen_in_the_folder() -> None:
    item = _item()
    select_art(item, ServerAsset.POSTER, URL)
    record_written(item, ServerAsset.POSTER, _file())

    clear_selection(item, ServerAsset.POSTER)

    asset = read_asset(item, ServerAsset.POSTER)
    assert (asset.url, asset.content_hash, asset.status) == (
        None,
        None,
        AssetStatus.PARTIAL,
    )
    assert local_file(asset) == _file()


def test_a_moved_folder_forgets_the_files_seen_in_the_old_one() -> None:
    item = _item()
    select_art(item, ServerAsset.POSTER, URL)
    record_written(item, ServerAsset.POSTER, _file())

    place_local(item, (ServerAsset.POSTER,), folder=True, moved=True)

    assert local_file(read_asset(item, ServerAsset.POSTER)) is None
    assert _status(item, ServerAsset.POSTER) is AssetStatus.PARTIAL


async def test_a_moved_folder_is_stored_on_the_same_delivery(
    db_session: AsyncSession,
) -> None:
    """Only one local delivery may exist, so a move cannot replace the row."""
    item = MediaItem(media_type=MediaType.MOVIE, title="Alien", folder_path="/m")
    place_local(item, (ServerAsset.POSTER,), folder=True)
    select_art(item, ServerAsset.POSTER, URL)
    record_written(item, ServerAsset.POSTER, _file())
    db_session.add(item)
    await db_session.flush()
    [before] = read_asset(item, ServerAsset.POSTER).deliveries

    place_local(item, (ServerAsset.POSTER,), folder=True, moved=True)
    await db_session.flush()

    assert read_asset(item, ServerAsset.POSTER).deliveries == [before]
    assert local_file(read_asset(item, ServerAsset.POSTER)) is None


#: What the copy named the poster when Overture confirmed it there.
UPLOADED_REF = "/thumb/1"


def _uploaded(collection: MediaCollection) -> None:
    place(collection, ServerAsset.POSTER, (COPY,))
    select_art(collection, ServerAsset.POSTER, URL, poster_style=None)
    record_content(collection, ServerAsset.POSTER, ContentFacts("up", "0" * 64))
    confirm_delivery(collection, ServerAsset.POSTER, COPY, ref=UPLOADED_REF)


def test_a_collection_is_complete_while_every_copy_shows_its_content() -> None:
    collection = MediaCollection(id=2, title="Saga")
    _uploaded(collection)
    assert _status(collection, ServerAsset.POSTER) is AssetStatus.COMPLETE

    other = Destination(2, "box", DeliveryChannel.UPLOAD)
    place(collection, ServerAsset.POSTER, (COPY, other))
    assert _status(collection, ServerAsset.POSTER) is AssetStatus.PARTIAL


@pytest.mark.parametrize(
    ("evidence", "status", "ref"),
    [
        (Evidence.SAME, AssetStatus.COMPLETE, "/thumb/2"),
        (Evidence.UNKNOWN, AssetStatus.COMPLETE, UPLOADED_REF),
        (Evidence.DIFFERENT, AssetStatus.PARTIAL, "/thumb/2"),
    ],
)
def test_only_evidence_of_another_image_takes_a_copys_content(
    evidence: Evidence, status: AssetStatus, ref: str
) -> None:
    """A copy that could not be read proves nothing, so it keeps what it held.

    It keeps the ref it was confirmed under too, so the next check reads it.
    """
    collection = MediaCollection(id=2, title="Saga")
    _uploaded(collection)

    observe(collection, ServerAsset.POSTER, COPY, evidence, ref="/thumb/2")

    assert _status(collection, ServerAsset.POSTER) is status
    assert read_asset(collection, ServerAsset.POSTER).deliveries[0].observed_ref == ref


def test_an_asset_nothing_is_wanted_for_is_complete_as_it_is() -> None:
    collection = MediaCollection(id=2, title="Saga")

    set_needed(collection, ServerAsset.THEME, False)
    assert _status(collection, ServerAsset.THEME) is AssetStatus.COMPLETE

    set_needed(collection, ServerAsset.THEME, True)
    assert _status(collection, ServerAsset.THEME) is AssetStatus.MISSING


def test_a_theme_selection_follows_the_same_rule() -> None:
    item = _item()
    place_local(item, (ServerAsset.THEME,), folder=True)
    select_theme(item, "yt", source=ThemeIdSource.SELECTION, title=None, duration=None)
    assert _status(item, ServerAsset.THEME) is AssetStatus.PARTIAL

    record_written(item, ServerAsset.THEME, _file("audio"))
    assert _status(item, ServerAsset.THEME) is AssetStatus.COMPLETE

    clear_selection(item, ServerAsset.THEME)
    assert read_asset(item, ServerAsset.THEME).provenance_cleared


def test_a_shows_art_needs_a_complete_poster_for_every_tracked_season() -> None:
    show = MediaItem(id=1, media_type=MediaType.SHOW, title="Firefly")
    for kind in (ServerAsset.POSTER, ServerAsset.BACKGROUND):
        select_art(show, kind, URL)
    seasons = [Season(id=n, media_item_id=1, season_num=n) for n in (1, 2)]
    select_art(seasons[0], ServerAsset.SEASON_POSTER, URL)

    art = item_art_status(show, seasons)
    assert (art.art, art.season_posters) == (AssetStatus.PARTIAL, AssetStatus.PARTIAL)

    select_art(seasons[1], ServerAsset.SEASON_POSTER, URL)
    assert item_art_status(show, seasons).art is AssetStatus.COMPLETE
    assert item_art_status(show, []).season_posters is AssetStatus.MISSING


def test_statuses_combine_to_complete_only_when_all_are() -> None:
    complete, partial, missing = AssetStatus
    assert combined_status([complete, complete]) is complete
    assert combined_status([complete, missing]) is partial
    assert combined_status([missing, missing]) is missing
    assert combined_status([]) is missing


LOCAL_COPY = Destination(3, "folder", DeliveryChannel.FILE)
OTHER_COPY = Destination(2, "box", DeliveryChannel.UPLOAD)


def _row(
    observed_hash: str | None = None,
    observed_ref: str | None = None,
    *,
    required: bool = True,
) -> AssetDelivery:
    return AssetDelivery(
        asset_id=1,
        server_id=1,
        server_item_id="box",
        channel=DeliveryChannel.UPLOAD,
        required=required,
        observed_hash=observed_hash,
        observed_ref=observed_ref,
    )


@pytest.mark.parametrize(
    ("asset", "status"),
    [
        (Asset(kind=ServerAsset.POSTER), AssetStatus.MISSING),
        (Asset(kind=ServerAsset.POSTER, needed=False), AssetStatus.COMPLETE),
        (Asset(kind=ServerAsset.POSTER, url=URL), AssetStatus.COMPLETE),
        (Asset(kind=ServerAsset.POSTER, content_hash="a"), AssetStatus.PARTIAL),
        (
            Asset(kind=ServerAsset.POSTER, url=URL, deliveries=[_row()]),
            AssetStatus.PARTIAL,
        ),
        (
            Asset(
                kind=ServerAsset.POSTER,
                url=URL,
                content_hash="a",
                deliveries=[_row("a"), _row("b")],
            ),
            AssetStatus.PARTIAL,
        ),
        (
            Asset(
                kind=ServerAsset.POSTER,
                url=URL,
                content_hash="a",
                deliveries=[_row("a"), _row("b", required=False)],
            ),
            AssetStatus.COMPLETE,
        ),
        # A delivery matches only content Overture holds.
        (
            Asset(kind=ServerAsset.POSTER, url=URL, deliveries=[_row(None)]),
            AssetStatus.PARTIAL,
        ),
        # Anything seen at a destination, even another image, starts the asset.
        (Asset(kind=ServerAsset.POSTER, deliveries=[_row("b")]), AssetStatus.PARTIAL),
        (
            Asset(kind=ServerAsset.POSTER, deliveries=[_row(None, "/thumb")]),
            AssetStatus.PARTIAL,
        ),
        (Asset(kind=ServerAsset.POSTER, deliveries=[_row()]), AssetStatus.MISSING),
    ],
)
def test_the_status_rule(asset: Asset, status: AssetStatus) -> None:
    assert settled_status(asset) is status


def test_an_absent_file_places_no_destination() -> None:
    collection = MediaCollection(id=2, title="Saga")
    select_art(collection, ServerAsset.POSTER, URL)

    record_file(collection, ServerAsset.POSTER, None, destination=LOCAL_COPY)

    assert read_asset(collection, ServerAsset.POSTER).deliveries == []
    assert _status(collection, ServerAsset.POSTER) is AssetStatus.COMPLETE
    assert (
        record_file(MediaCollection(id=3, title="Other"), ServerAsset.POSTER, None)
        is None
    )


def test_an_absent_file_forgets_what_was_seen_at_its_destination() -> None:
    item = _item()
    record_file(item, ServerAsset.POSTER, _file())

    record_file(item, ServerAsset.POSTER, None)

    assert local_file(read_asset(item, ServerAsset.POSTER)) is None
    assert _status(item, ServerAsset.POSTER) is AssetStatus.MISSING


def test_only_content_overture_holds_can_be_delivered() -> None:
    collection = MediaCollection(id=2, title="Saga")
    select_art(collection, ServerAsset.POSTER, URL)

    with pytest.raises(ValueError, match="content"):
        confirm_delivery(collection, ServerAsset.POSTER, COPY, ref=None)


def test_placing_drops_unlisted_destinations_and_forgets_a_changed_channel() -> None:
    collection = MediaCollection(id=2, title="Saga")
    _uploaded(collection)
    place(collection, ServerAsset.POSTER, (COPY, OTHER_COPY))
    record_file(collection, ServerAsset.POSTER, _file("up"), destination=OTHER_COPY)

    place(
        collection,
        ServerAsset.POSTER,
        (Destination(COPY.server_id, COPY.server_item_id, DeliveryChannel.FILE),),
    )

    asset = read_asset(collection, ServerAsset.POSTER)
    assert [(row.server_id, row.observed_hash) for row in asset.deliveries] == [
        (1, None)
    ]
    assert asset.status is AssetStatus.PARTIAL


def test_clearing_art_that_was_never_recorded_writes_nothing() -> None:
    item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien")

    clear_selection(item, ServerAsset.POSTER)

    assert item.assets == []


def test_a_generated_upload_records_how_it_was_drawn() -> None:
    item = _item()
    generated = ArtGeneration(ArtStyle.DARK, title_only=True)

    asset = select_upload(item, ServerAsset.POSTER, "hash", generated=generated)

    assert generation(asset) == generated
    select_art(item, ServerAsset.POSTER, URL)
    assert generation(asset) is None


def test_observing_a_destination_never_placed_records_nothing() -> None:
    collection = MediaCollection(id=2, title="Saga")
    _uploaded(collection)

    observe(collection, ServerAsset.POSTER, OTHER_COPY, Evidence.DIFFERENT, ref="x")

    assert len(read_asset(collection, ServerAsset.POSTER).deliveries) == 1
    assert _status(collection, ServerAsset.POSTER) is AssetStatus.COMPLETE


async def test_a_flush_refuses_a_status_written_outside_the_ledger(
    db_session: AsyncSession,
) -> None:
    item = MediaItem(media_type=MediaType.MOVIE, title="Alien", folder_path="/m")
    place_local(item, (ServerAsset.POSTER,), folder=True)
    db_session.add(item)
    await db_session.flush()
    asset = read_asset(item, ServerAsset.POSTER)

    asset.status = AssetStatus.COMPLETE

    with pytest.raises(RuntimeError, match="outside the ledger"):
        await db_session.flush()
