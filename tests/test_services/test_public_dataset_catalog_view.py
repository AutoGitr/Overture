"""Browsing the whole catalog, drafting changes to it and contributing them."""

lazy import json
lazy from pathlib import Path
lazy from typing import Any
lazy from zipfile import ZipFile

lazy import pytest
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    CatalogMediaType,
    MediaType,
    ServerType,
    ThemeBulkSource,
)
lazy from overture.schemas.public_dataset import (
    CatalogDraftUpdate,
    CatalogSeason,
    PublicDatasetSyncStats,
)
lazy from overture.services.public_dataset import staging
lazy from overture.services.public_dataset.browse import CatalogBrowser
lazy from overture.services.public_dataset.export import export_selections
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.test_services.test_public_dataset_edges import (
    catalog_jsonl,
    catalog_payload,
)

pytestmark = pytest.mark.usefixtures("public_art_hosts")

COLLECTION: dict[str, Any] = {
    "media_type": "collection",
    "title": "Star Wars Collection",
    "tmdb_id": 10,
    "poster_url": None,
    "background_url": None,
    "youtube_id_overturedb": None,
    "youtube_id_themerrdb": "JG5OsfOuEy0",
}


async def _import_catalog(
    session: AsyncSession, tmp_path: Path, app_config: Settings
) -> PublicDatasetSyncStats:
    payload = catalog_payload()
    payload["entries"].append(COLLECTION)
    path, stage = tmp_path / "catalog.jsonl", tmp_path / "stage.sqlite"
    path.write_bytes(catalog_jsonl(payload))
    await staging.prepare(path, stage, app_config=app_config)
    stats = PublicDatasetSyncStats()
    await staging.replace(session, stage, utc_now(), stats)
    await session.commit()
    return stats


@pytest.fixture
async def browser(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> CatalogBrowser:
    await _import_catalog(db_session, tmp_path, app_config)
    await enable_public_dataset(db_session)
    return CatalogBrowser(database=database, app_config=app_config)


async def test_collection_entries_are_stored_apart_from_titles(
    db_session: AsyncSession, tmp_path: Path, *, app_config: Settings
) -> None:
    stats = await _import_catalog(db_session, tmp_path, app_config)

    assert (stats.items, stats.movies, stats.shows, stats.collections) == (2, 1, 1, 1)
    (collection,) = (await db_session.exec(select(PublicDatasetCollection))).all()
    assert (collection.tmdb_id, collection.youtube_id_themerrdb) == (
        10,
        "JG5OsfOuEy0",
    )


async def test_the_catalog_view_needs_overturedb_enabled(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _import_catalog(db_session, tmp_path, app_config)
    browser = CatalogBrowser(database=database, app_config=app_config)

    with pytest.raises(PublicServiceError) as exc_info:
        await browser.list_entries(CatalogMediaType.MOVIE)
    assert exc_info.value.status_code == 409


async def test_rows_link_to_what_the_library_holds(
    db_session: AsyncSession, browser: CatalogBrowser
) -> None:
    movie = MediaItem(media_type=MediaType.MOVIE, title="Heat", imdb_id="tt0113277")
    db_session.add(movie)
    db_session.add(
        MediaCollection(
            server_item_id="saga",
            media_type=MediaType.MOVIE,
            server_type=ServerType.PLEX,
            tmdb_collection_id=10,
            last_synced_at=utc_now(),
        )
    )
    await db_session.commit()

    (heat,) = await browser.list_entries(CatalogMediaType.MOVIE)
    (show,) = await browser.list_entries(CatalogMediaType.SHOW)
    (saga,) = await browser.list_entries(CatalogMediaType.COLLECTION)

    assert (heat.entry_key, heat.library_item_id) == ("tmdb-949", movie.id)
    assert (show.entry_key, show.season_posters, show.library_item_id) == (
        "tmdb-1396",
        2,
        None,
    )
    assert show.poster_preview_url == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert (saga.entry_key, saga.library_collection_id) == ("tmdb-10", 1)


async def test_any_identity_finds_an_entry_under_its_canonical_name(
    browser: CatalogBrowser,
) -> None:
    detail = await browser.get_entry(CatalogMediaType.SHOW, "tvdb-81189")

    assert detail.entry_key == "tmdb-1396"
    assert detail.entry.seasons is not None
    assert [season.season_num for season in detail.entry.seasons] == [0, 1]
    for key in ("tmdb-949", "nonsense", "tmdb-0"):
        with pytest.raises(PublicServiceError) as exc_info:
            await browser.get_entry(CatalogMediaType.SHOW, key)
        assert exc_info.value.status_code == 404


async def test_drafts_hold_valid_changes_until_they_match_the_entry(
    browser: CatalogBrowser,
) -> None:
    resized = "https://image.tmdb.org/t/p/w500/new.jpg"
    saved = await browser.save_draft(
        CatalogMediaType.SHOW,
        "tmdb-1396",
        CatalogDraftUpdate(
            poster_url=resized,
            seasons=[CatalogSeason(season_num=2, poster_url=resized)],
        ),
    )

    assert saved.draft is not None
    assert saved.draft.poster_url == "https://image.tmdb.org/t/p/original/new.jpg"
    assert saved.entry.poster_url == "https://image.tmdb.org/t/p/original/poster.jpg"
    (row,) = await browser.list_entries(CatalogMediaType.SHOW)
    assert row.has_draft is True
    assert row.poster_url == saved.draft.poster_url
    assert row.poster_preview_url == "https://image.tmdb.org/t/p/w342/new.jpg"
    assert row.season_posters == 1

    with pytest.raises(PublicServiceError) as exc_info:
        await browser.save_draft(
            CatalogMediaType.SHOW,
            "tmdb-1396",
            CatalogDraftUpdate(youtube_id_overturedb="secondary12"),
        )
    assert exc_info.value.status_code == 422

    reverted = await browser.save_draft(
        CatalogMediaType.SHOW,
        "tmdb-1396",
        CatalogDraftUpdate(
            poster_url=saved.entry.poster_url,
            seasons=saved.entry.seasons,
        ),
    )
    assert reverted.draft is None
    (row,) = await browser.list_entries(CatalogMediaType.SHOW)
    assert row.has_draft is False
    assert row.poster_url == saved.entry.poster_url


async def test_collection_drafts_take_only_collection_fields(
    browser: CatalogBrowser,
) -> None:
    with pytest.raises(PublicServiceError, match="no year"):
        await browser.save_draft(
            CatalogMediaType.COLLECTION, "tmdb-10", CatalogDraftUpdate(year=1977)
        )

    saved = await browser.save_draft(
        CatalogMediaType.COLLECTION,
        "tmdb-10",
        CatalogDraftUpdate(youtube_id_overturedb="abcDEF12345"),
    )
    assert saved.draft is not None
    discarded = await browser.discard_draft(CatalogMediaType.COLLECTION, "tmdb-10")
    assert discarded.draft is None


async def test_export_puts_drafts_first_then_selections_and_collection_themes(
    db_session: AsyncSession,
    tmp_path: Path,
    browser: CatalogBrowser,
    database: Database,
) -> None:
    await browser.save_draft(
        CatalogMediaType.MOVIE,
        "tmdb-949",
        CatalogDraftUpdate(youtube_id_overturedb="draftTheme1"),
    )
    db_session.add_all(
        [
            MediaItem(
                media_type=MediaType.MOVIE,
                title="Heat",
                tmdb_id=949,
                youtube_id="libraryThm1",
            ),
            MediaCollection(
                server_item_id="saga",
                media_type=MediaType.MOVIE,
                server_type=ServerType.PLEX,
                title="Star Wars",
                tmdb_collection_id=10,
                youtube_id="collection1",
                last_synced_at=utc_now(),
            ),
        ]
    )
    await db_session.commit()

    directory = tmp_path / "export"
    directory.mkdir()
    with ZipFile(await export_selections(database, directory)) as archive:
        files = {name: json.loads(archive.read(name)) for name in archive.namelist()}

    assert set(files) == {"data/movies/tmdb-949.json", "data/collections/tmdb-10.json"}
    assert files["data/movies/tmdb-949.json"]["youtube_id_overturedb"] == "draftTheme1"
    assert files["data/collections/tmdb-10.json"] == {
        **COLLECTION,
        "youtube_id_overturedb": "collection1",
        "youtube_id_themerrdb": None,
    }


async def test_correcting_a_drafts_only_identity_keeps_it_editable_and_exportable(
    browser: CatalogBrowser,
    db_session: AsyncSession,
    database: Database,
    tmp_path: Path,
) -> None:
    saved = await browser.save_draft(
        CatalogMediaType.COLLECTION, "tmdb-10", CatalogDraftUpdate(tmdb_id=11)
    )
    assert saved.draft is not None
    assert saved.draft.tmdb_id == 11
    (row,) = await browser.list_entries(CatalogMediaType.COLLECTION)
    assert row.has_draft
    assert row.entry_key == "tmdb-10"
    assert row.tmdb_id == 11
    saved = await browser.save_draft(
        CatalogMediaType.COLLECTION,
        "tmdb-10",
        CatalogDraftUpdate(title="Corrected title"),
    )
    assert saved.draft is not None
    assert saved.draft.tmdb_id == 11
    db_session.add(
        MediaCollection(
            server_item_id="saga",
            server_type=ServerType.PLEX,
            media_type=MediaType.MOVIE,
            title="Old title",
            tmdb_collection_id=10,
            youtube_id="collection1",
            last_synced_at=utc_now(),
        )
    )
    await db_session.commit()
    directory = tmp_path / "draft-export"
    directory.mkdir()
    with ZipFile(await export_selections(database, directory)) as archive:
        assert archive.namelist() == ["data/collections/tmdb-11.json"]
        assert (
            json.loads(archive.read(archive.namelist()[0]))["title"]
            == "Corrected title"
        )
    assert (await browser.counts()).drafts == 1
    assert (
        await browser.discard_draft(CatalogMediaType.COLLECTION, "tmdb-10")
    ).draft is None
    assert (await browser.counts()).drafts == 0


async def test_export_preserves_themerrdb_attribution_after_the_catalog_is_cleared(
    db_session: AsyncSession, database: Database, tmp_path: Path
) -> None:
    db_session.add(
        MediaCollection(
            server_item_id="saga",
            server_type=ServerType.PLEX,
            media_type=MediaType.MOVIE,
            title="Saga",
            tmdb_collection_id=10,
            youtube_id="JG5OsfOuEy0",
            youtube_id_source=ThemeBulkSource.THEMERRDB,
            last_synced_at=utc_now(),
        )
    )
    await db_session.commit()
    with ZipFile(await export_selections(database, tmp_path)) as archive:
        assert not any(
            name.startswith("data/collections/") for name in archive.namelist()
        )
