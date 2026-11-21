"""Regression coverage for bulk contribution archives."""

lazy import json
lazy from pathlib import Path
lazy from zipfile import ZipFile

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.catalog_contract.contract import validate_entries
lazy from overture.db.ledger import select_art, select_theme
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    CollectionPosterStyle,
    MediaType,
    ServerAsset,
    ThemeBulkSource,
    ThemeIdSource,
)
lazy from overture.services.catalog.export import (
    REPORT_NAME,
    export_archive,
    export_selections,
)
lazy from overture.utils.art_urls import PublicArtUrl, art_refusals
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import seed_theme


async def test_export_reads_saved_season_art_and_omits_private_fields(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    movie = seed_theme(
        MediaItem(
            media_type=MediaType.MOVIE,
            title="Movie",
            tmdb_id=12,
            folder_path="/private/movie",
        ),
        "abcdefghijk",
    )
    show = MediaItem(media_type=MediaType.SHOW, title="Show", tmdb_id=99, tvdb_id=12)
    db_session.add_all([movie, show])
    await db_session.flush()
    assert show.id is not None
    season = Season(media_item_id=show.id, season_num=0)
    select_art(
        season,
        ServerAsset.SEASON_POSTER,
        PublicArtUrl("https://image.tmdb.org/t/p/original/test.jpg"),
    )
    db_session.add(season)
    await db_session.commit()
    with ZipFile(await export_selections(database, tmp_path)) as archive:
        assert set(archive.namelist()) == {
            "data/movies/tmdb-12.json",
            "data/shows/tmdb-99.json",
        }
        entries = [
            json.loads(archive.read(path))
            for path in archive.namelist()
            if path.endswith(".json")
        ]
        validate_entries(entries)
        assert entries[1]["seasons"] == [
            {
                "season_num": 0,
                "poster_url": "https://image.tmdb.org/t/p/original/test.jpg",
            }
        ]
        assert "seasons" not in entries[0]
        assert entries[0]["youtube_id_overturedb"] == "abcdefghijk"
        assert entries[0]["youtube_id_themerrdb"] is None


async def test_export_omits_invalid_entries_and_ignores_empty_selections(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    invalid = seed_theme(
        MediaItem(
            media_type=MediaType.MOVIE,
            title="Missing ID",
            year=2001,
        ),
        "abcdefghijk",
    )
    empty = MediaItem(media_type=MediaType.MOVIE, title="Empty", tmdb_id=1)
    db_session.add_all([invalid, empty])
    await db_session.commit()
    with ZipFile(await export_selections(database, tmp_path)) as archive:
        assert archive.namelist() == []


async def test_export_rejects_conflicting_identities_instead_of_overwriting(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    items = [
        seed_theme(
            MediaItem(media_type=MediaType.MOVIE, title=title, tmdb_id=1), "abcdefghijk"
        )
        for title in ("One", "Two")
    ]
    db_session.add_all(items)
    await db_session.commit()
    with pytest.raises(PublicServiceError, match="conflicting library selections"):
        await export_selections(database, tmp_path)


async def test_export_filters_unallowed_art_hosts_and_skips_unsupported(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    mixed = MediaItem(
        media_type=MediaType.MOVIE,
        title="Mixed Art",
        tmdb_id=10,
    )
    select_art(
        mixed,
        ServerAsset.POSTER,
        PublicArtUrl("https://m.media-amazon.com/images/M/unallowed.jpg"),
    )
    select_art(
        mixed,
        ServerAsset.BACKGROUND,
        PublicArtUrl("https://image.tmdb.org/t/p/original/valid_bg.jpg"),
    )

    unsupported_only = MediaItem(
        media_type=MediaType.MOVIE,
        title="Amazon Only",
        tmdb_id=20,
    )
    select_art(
        unsupported_only,
        ServerAsset.POSTER,
        PublicArtUrl("https://m.media-amazon.com/images/M/unallowed2.jpg"),
    )
    db_session.add_all([mixed, unsupported_only])
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        assert set(archive.namelist()) == {"data/movies/tmdb-10.json", REPORT_NAME}
        report = archive.read(REPORT_NAME).decode()
        assert (
            "Mixed Art: Poster: OvertureDB won't accept art from m.media-amazon.com"
            in (report)
        )
        assert "Amazon Only: Poster:" in report
        entry = json.loads(archive.read("data/movies/tmdb-10.json"))
        validate_entries([entry])
        assert entry["poster_url"] is None
        assert (
            entry["background_url"]
            == "https://image.tmdb.org/t/p/original/valid_bg.jpg"
        )


async def test_export_archive_cleans_up_on_failure(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    items = [
        seed_theme(
            MediaItem(media_type=MediaType.MOVIE, title=title, tmdb_id=1), "abcdefghijk"
        )
        for title in ("One", "Two")
    ]
    db_session.add_all(items)
    await db_session.commit()
    with pytest.raises(PublicServiceError):
        await export_archive(database, config_dir)
    assert list(config_dir.iterdir()) == []


async def test_export_carries_collection_art_without_a_themerrdb_theme(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    collection = seed_theme(
        stored_collection(
            server_item_id="saga",
            media_type=MediaType.MOVIE,
            title="Saga",
            tmdb_collection_id=10,
            last_synced_at=utc_now(),
        ),
        "themerrdb01",
    )
    db_session.add(
        CatalogCollection(tmdb_id=10, title="Saga", youtube_id_themerrdb="themerrdb01")
    )
    select_art(
        collection,
        ServerAsset.POSTER,
        PublicArtUrl("https://image.tmdb.org/t/p/w500/saga.jpg"),
        poster_style=CollectionPosterStyle.INDIVIDUAL,
    )
    db_session.add(collection)
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        entry = json.loads(archive.read("data/collections/tmdb-10.json"))

    assert (
        entry["poster_url_individual"] == "https://image.tmdb.org/t/p/original/saga.jpg"
    )
    assert entry["poster_url_matte"] is None
    assert entry["poster_url_overlay"] is None
    assert entry["background_url"] is None
    assert entry["youtube_id_overturedb"] is None


async def test_export_leaves_out_a_theme_found_in_themerrdb_after_the_catalog_moves(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    collection = stored_collection(
        server_item_id="saga",
        media_type=MediaType.MOVIE,
        title="Saga",
        tmdb_collection_id=10,
        last_synced_at=utc_now(),
    )
    select_theme(
        collection,
        "themerrdb01",
        source=ThemeIdSource.DOWNLOAD,
        title=None,
        duration=None,
        found_by=ThemeBulkSource.THEMERRDB,
    )
    select_art(
        collection,
        ServerAsset.POSTER,
        PublicArtUrl("https://image.tmdb.org/t/p/w500/saga.jpg"),
        poster_style=CollectionPosterStyle.INDIVIDUAL,
    )
    # ThemerrDB has moved on to another video since.
    db_session.add(
        CatalogCollection(tmdb_id=10, title="Saga", youtube_id_themerrdb="newer000001")
    )
    db_session.add(collection)
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        entry = json.loads(archive.read("data/collections/tmdb-10.json"))

    assert entry["youtube_id_overturedb"] is None


def test_export_names_art_from_a_host_overturedb_refuses() -> None:
    warning = (
        "Poster: OvertureDB won't accept art from m.media-amazon.com; it accepts "
        "TMDB, TPDb, fanart.tv, TVDB and Plex"
    )
    assert art_refusals(
        "https://m.media-amazon.com/images/M/a.jpg",
        "https://image.tmdb.org/t/p/original/b.jpg",
    ) == [warning]


@pytest.mark.parametrize(("seconds", "kept"), [(19, False), (20, True), (601, False)])
async def test_export_leaves_out_a_theme_overturedb_refuses_for_its_length(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
    seconds: int,
    kept: bool,
) -> None:
    item = seed_theme(
        MediaItem(
            media_type=MediaType.MOVIE,
            title="Theme",
            tmdb_id=10,
        ),
        "dQw4w9WgXcQ",
        duration=seconds,
    )
    select_art(
        item,
        ServerAsset.POSTER,
        PublicArtUrl("https://image.tmdb.org/t/p/original/a.jpg"),
    )
    db_session.add(item)
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        entry = json.loads(archive.read("data/movies/tmdb-10.json"))
        report = (
            archive.read(REPORT_NAME).decode()
            if REPORT_NAME in archive.namelist()
            else ""
        )
    assert (entry["youtube_id_overturedb"] == "dQw4w9WgXcQ") is kept
    assert (f"Theme: Theme: {seconds} seconds long" in report) is not kept
