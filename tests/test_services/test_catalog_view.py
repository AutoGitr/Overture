"""Browsing the whole catalog, drafting changes to it and contributing them."""

lazy import json
lazy from pathlib import Path
lazy from typing import Any
lazy from zipfile import ZipFile

lazy import pytest
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import Destination, Evidence, observe, place, read_asset
lazy from overture.db.models.catalog import (
    CatalogCollection,
    CatalogDraft,
)
lazy from overture.db.models.media_collection import CollectionLibrary
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.settings import get_app_settings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    AssetStatus,
    CatalogMediaType,
    CollectionPosterStyle,
    DeliveryChannel,
    MediaType,
    ServerAsset,
)
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.bulk import BulkThemeRequest
lazy from overture.schemas.catalog import (
    CatalogDraftsDiscard,
    CatalogDraftUpdate,
    CatalogSeason,
    CatalogSyncStats,
)
lazy from overture.schemas.collections import collection_read
lazy from overture.services.asset_runs.plan import plan_run
lazy from overture.services.catalog import staging
lazy from overture.services.catalog.browse import CatalogBrowser
lazy from overture.services.catalog.export import export_selections
lazy from overture.services.catalog.index import NO_THEME
lazy from overture.services.needs import apply_needs
lazy from overture.services.schedule_store import (
    CATALOG_SCHEDULE,
    save_schedule,
)
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.hashing import text_digest
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_catalog
lazy from tests.collection_helpers import managing_rule, stored_collection
lazy from tests.factories import seed_asset, seed_theme
lazy from tests.test_services.test_catalog_edges import (
    catalog_jsonl,
    catalog_payload,
)

COLLECTION: dict[str, Any] = {
    "media_type": "collection",
    "title": "Star Wars Collection",
    "tmdb_id": 10,
    "poster_url_individual": None,
    "poster_url_matte": None,
    "poster_url_overlay": None,
    "background_url": None,
    "youtube_id_overturedb": None,
    "youtube_id_themerrdb": "JG5OsfOuEy0",
}


async def _import_catalog(
    session: AsyncSession, tmp_path: Path, app_config: Settings
) -> CatalogSyncStats:
    payload = catalog_payload()
    payload["entries"].append(COLLECTION)
    path, stage = tmp_path / "catalog.jsonl", tmp_path / "stage.sqlite"
    path.write_bytes(catalog_jsonl(payload))
    await staging.prepare(path, stage, app_config=app_config)
    stats = CatalogSyncStats()
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
    await enable_catalog(db_session)
    return CatalogBrowser(database=database)


async def test_collection_entries_are_stored_apart_from_titles(
    db_session: AsyncSession, tmp_path: Path, *, app_config: Settings
) -> None:
    stats = await _import_catalog(db_session, tmp_path, app_config)

    assert (stats.items, stats.movies, stats.shows, stats.collections) == (2, 1, 1, 1)
    (collection,) = (await db_session.exec(select(CatalogCollection))).all()
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
    await save_schedule(db_session, CATALOG_SCHEDULE, enabled=False)
    await db_session.commit()
    browser = CatalogBrowser(database=database)

    with pytest.raises(PublicServiceError) as exc_info:
        await browser.list_entries(CatalogMediaType.MOVIE)
    assert exc_info.value.status_code == 409


async def test_rows_link_to_what_the_library_holds(
    db_session: AsyncSession, browser: CatalogBrowser
) -> None:
    movie = MediaItem(media_type=MediaType.MOVIE, title="Heat", imdb_id="tt0113277")
    db_session.add(movie)
    db_session.add(
        stored_collection(
            server_item_id="saga",
            media_type=MediaType.MOVIE,
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


async def test_rows_name_the_librarys_local_files_of_the_same_art(
    db_session: AsyncSession, browser: CatalogBrowser
) -> None:
    movie = MediaItem(media_type=MediaType.MOVIE, title="Heat", imdb_id="tt0113277")
    db_session.add(movie)
    await db_session.flush()
    for art_type, url, content in (
        # A TMDB link of another size names the same image.
        (ArtType.POSTER, "https://image.tmdb.org/t/p/w500/heat.jpg", None),
        # A file replaced outside Overture no longer holds the selection.
        (ArtType.BACKGROUND, "https://image.tmdb.org/t/p/original/b.jpg", "c" * 64),
    ):
        seed_asset(movie, art_type, url=url, file_hash="a" * 64, content_hash=content)
    await db_session.commit()

    (heat,) = await browser.list_entries(CatalogMediaType.MOVIE)
    detail = await browser.get_entry(CatalogMediaType.MOVIE, "tmdb-949")

    assert heat.local_art == {"https://image.tmdb.org/t/p/original/heat.jpg": "a" * 64}
    assert detail.local_art == heat.local_art


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


async def test_collection_rows_show_the_poster_style_asked_for(
    browser: CatalogBrowser, db_session: AsyncSession
) -> None:
    matte = "https://image.tmdb.org/t/p/original/matte.jpg"

    saved = await browser.save_draft(
        CatalogMediaType.COLLECTION,
        "tmdb-10",
        CatalogDraftUpdate(poster_url_matte=matte),
    )

    assert saved.draft is not None
    assert saved.draft.poster_url_matte == matte
    (draft,) = (await db_session.exec(select(CatalogDraft))).all()
    assert draft.entry["poster_url_matte"] == matte
    rows = {
        style: await browser.list_entries(CatalogMediaType.COLLECTION, posters=style)
        for style in CollectionPosterStyle
    }
    assert {style: row.poster_url for style, [row] in rows.items()} == {
        CollectionPosterStyle.INDIVIDUAL: None,
        CollectionPosterStyle.MATTE: matte,
        CollectionPosterStyle.OVERLAY: None,
    }


async def test_a_collection_draft_has_no_plain_poster(browser: CatalogBrowser) -> None:
    with pytest.raises(PublicServiceError, match="has no poster_url"):
        await browser.save_draft(
            CatalogMediaType.COLLECTION,
            "tmdb-10",
            CatalogDraftUpdate(poster_url="https://image.tmdb.org/t/p/original/p.jpg"),
        )


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
            seed_theme(
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Heat",
                    tmdb_id=949,
                ),
                "libraryThm1",
            ),
            seed_theme(
                stored_collection(
                    server_item_id="saga",
                    media_type=MediaType.MOVIE,
                    title="Star Wars",
                    tmdb_collection_id=10,
                    last_synced_at=utc_now(),
                ),
                "collection1",
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
        seed_theme(
            stored_collection(
                server_item_id="saga",
                media_type=MediaType.MOVIE,
                title="Old title",
                tmdb_collection_id=10,
                last_synced_at=utc_now(),
            ),
            "collection1",
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


async def test_bulk_discard_removes_the_named_drafts_and_skips_the_rest(
    browser: CatalogBrowser,
) -> None:
    await browser.save_draft(
        CatalogMediaType.SHOW,
        "tmdb-1396",
        CatalogDraftUpdate(poster_url="https://image.tmdb.org/t/p/original/new.jpg"),
    )

    result = await browser.discard_drafts(
        CatalogMediaType.SHOW,
        CatalogDraftsDiscard(entry_keys=["tmdb-1396", "tmdb-1396", "tmdb-949", "x"]),
    )

    assert result.discarded == 1
    (row,) = await browser.list_entries(CatalogMediaType.SHOW)
    assert row.has_draft is False


async def test_no_theme_is_imported_drafted_and_skipped_by_theme_runs(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    payload = catalog_payload()
    payload["entries"].append(
        {**COLLECTION, "youtube_id_themerrdb": None, "no_theme": True}
    )
    path, stage = tmp_path / "catalog.jsonl", tmp_path / "stage.sqlite"
    path.write_bytes(catalog_jsonl(payload))
    await staging.prepare(path, stage, app_config=app_config)
    await staging.replace(db_session, stage, utc_now(), CatalogSyncStats())
    await enable_catalog(db_session)
    db_session.add(
        stored_collection(
            id=1,
            server_item_id="saga",
            media_type=MediaType.MOVIE,
            title="Star Wars",
            tmdb_collection_id=10,
            last_synced_at=utc_now(),
        )
    )
    await db_session.flush()
    db_session.add(managing_rule(1))
    await db_session.commit()
    browser = CatalogBrowser(database=database)

    detail = await browser.get_entry(CatalogMediaType.COLLECTION, "tmdb-10")
    assert detail.entry.no_theme is True
    # A catalog sync records that the collection needs no theme.
    async with database.write_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        await apply_needs(session, collections=[row])
    plan = await plan_run(BulkThemeRequest(collection_ids=[1]), database=database)
    assert dict(plan.decided) == {(True, JobOutcome.SKIPPED, NO_THEME): 1}

    drafted = await browser.save_draft(
        CatalogMediaType.SHOW, "tmdb-1396", CatalogDraftUpdate(no_theme=True)
    )
    assert drafted.draft is not None
    assert drafted.draft.no_theme is True
    assert drafted.draft.youtube_id_overturedb is None
    cleared = await browser.save_draft(
        CatalogMediaType.SHOW, "tmdb-1396", CatalogDraftUpdate(no_theme=False)
    )
    assert cleared.draft is None or not cleared.draft.no_theme


@pytest.mark.parametrize(
    ("no_theme", "themes", "needed"),
    [(True, True, False), (False, True, True), (False, False, False)],
)
async def test_a_collection_needs_no_theme_its_catalog_or_settings_rule_out(
    no_theme: bool,
    themes: bool,
    needed: bool,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """OvertureDB's trusted No theme flag, or its settings, leave it complete."""
    async with database.write_session() as session:
        await enable_catalog(session)
        entry = CatalogCollection(tmdb_id=10, title="Saga", no_theme=no_theme)
        session.add(entry)
        settings = await get_app_settings(session)
        settings.collection_themes = themes
        session.add(settings)
        row = stored_collection(
            id=1,
            server_item_id="saga",
            media_type=MediaType.MOVIE,
            title="Saga",
            tmdb_collection_id=10,
        )
        session.add(row)
        await session.flush()
        await apply_needs(session, collections=[row])

    theme = read_asset(row, ServerAsset.THEME)
    assert theme.needed is needed
    assert theme.status is (AssetStatus.MISSING if needed else AssetStatus.COMPLETE)
    read = collection_read(row, entry, None, copies=row.copies, trust_no_theme=True)
    assert read.assets.theme.needed is needed
    # Only the catalog's own flag completes its theme, never the collection's policy.
    assert read.catalog_complete is no_theme
    distrusted = collection_read(
        row, entry, None, copies=row.copies, trust_no_theme=False
    )
    assert distrusted.catalog_complete is False


def test_a_collection_names_the_image_its_lead_copy_shows() -> None:
    row = stored_collection(id=1, server_item_id="other", title="Saga")
    lead = CollectionLibrary(
        server_id=2,
        collection_id=1,
        library_id="2:library",
        media_type=MediaType.MOVIE,
        server_item_id="lead",
    )
    row.libraries.append(lead)
    copies = {
        ref: Destination(part.server_id, part.server_item_id, DeliveryChannel.UPLOAD)
        for part, ref in ((row.libraries[0], "/other.jpg"), (lead, "/lead.jpg"))
    }
    place(row, ServerAsset.POSTER, copies.values())
    for ref, copy in copies.items():
        observe(row, ServerAsset.POSTER, copy, Evidence.DIFFERENT, ref=ref)

    led = collection_read(row, None, None, copies=[lead], trust_no_theme=True)
    unheld = collection_read(row, None, None, copies=[], trust_no_theme=True)

    assert led.server_poster_version == text_digest("/lead.jpg", 16)
    assert unheld.server_poster_version is None
