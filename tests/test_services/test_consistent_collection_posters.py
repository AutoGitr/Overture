"""OvertureDB's consistent collection posters, taken and contributed as chosen."""

lazy import json
lazy from pathlib import Path
lazy from zipfile import ZipFile

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import select_art
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.settings import SETTINGS_ROW_ID, AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, CollectionPosterStyle, ServerAsset
lazy from overture.services.catalog.export import REPORT_NAME, export_selections
lazy from overture.services.catalog.index import CatalogIndex
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_catalog
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import seed_theme

INDIVIDUAL = "https://image.tmdb.org/t/p/original/own.jpg"
MATTE = "https://theposterdb.com/api/assets/668235"
OVERLAY = "https://theposterdb.com/api/assets/2503"


async def _choose(session: AsyncSession, *posters: CollectionPosterStyle) -> None:
    await session.merge(
        AppSettings(id=SETTINGS_ROW_ID, collection_overturedb_posters=list(posters))
    )
    await session.commit()


@pytest.mark.parametrize(
    ("posters", "expected"),
    [
        (CollectionPosterStyle.INDIVIDUAL, INDIVIDUAL),
        (CollectionPosterStyle.MATTE, MATTE),
        (CollectionPosterStyle.OVERLAY, OVERLAY),
    ],
)
async def test_a_collection_takes_the_poster_the_setting_chooses(
    db_session: AsyncSession,
    app_config: Settings,
    posters: CollectionPosterStyle,
    expected: str,
) -> None:
    await enable_catalog(db_session)
    await _choose(db_session, posters)
    db_session.add(
        CatalogCollection(
            tmdb_id=10,
            title="Saga",
            poster_url_individual=INDIVIDUAL,
            poster_url_matte=MATTE,
            poster_url_overlay=OVERLAY,
        )
    )
    row = stored_collection(title="Saga", tmdb_collection_id=10)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, ["group", "rule"])

    index = await CatalogIndex.build_collections(db_session, [row])

    assert index.collection_art(row, ArtType.POSTER).value == expected


@pytest.mark.parametrize(
    ("posters", "expected"),
    [
        ((CollectionPosterStyle.MATTE, CollectionPosterStyle.INDIVIDUAL), INDIVIDUAL),
        ((CollectionPosterStyle.OVERLAY, CollectionPosterStyle.MATTE), None),
        ((), None),
    ],
)
async def test_a_collection_takes_the_first_style_in_order_that_overturedb_holds(
    db_session: AsyncSession,
    app_config: Settings,
    posters: tuple[CollectionPosterStyle, ...],
    expected: str | None,
) -> None:
    await enable_catalog(db_session)
    await _choose(db_session, *posters)
    db_session.add(
        CatalogCollection(tmdb_id=10, title="Saga", poster_url_individual=INDIVIDUAL)
    )
    row = stored_collection(title="Saga", tmdb_collection_id=10)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, ["group", "rule"])

    index = await CatalogIndex.build_collections(db_session, [row])

    assert index.collection_art(row, ArtType.POSTER).value == expected
    assert index.collection_poster_style(row, ArtType.POSTER) == (
        CollectionPosterStyle.INDIVIDUAL if expected else None
    )


async def test_a_group_chooses_its_collections_posters_over_the_global_choice(
    db_session: AsyncSession, app_config: Settings
) -> None:
    await enable_catalog(db_session)
    await _choose(db_session, CollectionPosterStyle.INDIVIDUAL)
    db_session.add(
        CatalogCollection(
            tmdb_id=10,
            title="Saga",
            poster_url_individual=INDIVIDUAL,
            poster_url_matte=MATTE,
            poster_url_overlay=OVERLAY,
        )
    )
    row = stored_collection(title="Saga", tmdb_collection_id=10, group="Franchises")
    assert row.group is not None
    row.group.overturedb_posters = [CollectionPosterStyle.MATTE]
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, ["group", "rule"])

    index = await CatalogIndex.build_collections(db_session, [row])

    assert index.collection_art(row, ArtType.POSTER).value == MATTE


async def test_a_consistent_poster_is_contributed_as_one_from_tmdb_or_theposterdb(
    db_session: AsyncSession, tmp_path: Path, database: Database
) -> None:
    for tmdb_id, url in (
        (10, OVERLAY),
        (11, "https://assets.fanart.tv/fanart/a.jpg"),
    ):
        row = seed_theme(
            stored_collection(
                title=f"Saga {tmdb_id}",
                tmdb_collection_id=tmdb_id,
                last_synced_at=utc_now(),
            ),
            "dQw4w9WgXcQ",
        )
        select_art(
            row,
            ServerAsset.POSTER,
            PublicArtUrl(url),
            poster_style=CollectionPosterStyle.OVERLAY,
        )
        db_session.add(row)
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        taken = json.loads(archive.read("data/collections/tmdb-10.json"))
        refused = json.loads(archive.read("data/collections/tmdb-11.json"))
        report = archive.read(REPORT_NAME).decode()

    assert (
        taken["poster_url_individual"],
        taken["poster_url_matte"],
        taken["poster_url_overlay"],
    ) == (None, None, OVERLAY)
    # The theme still goes; only the poster a consistent one cannot be is left out.
    assert refused["poster_url_overlay"] is None
    assert refused["youtube_id_overturedb"] == "dQw4w9WgXcQ"
    assert "Saga 11: Poster: upload consistent posters to TMDB or TPDb" in report


async def test_a_poster_is_contributed_as_the_style_it_was_selected_as(
    db_session: AsyncSession, tmp_path: Path, database: Database
) -> None:
    row = stored_collection(
        title="Saga", tmdb_collection_id=10, last_synced_at=utc_now()
    )
    select_art(
        row,
        ServerAsset.POSTER,
        PublicArtUrl(INDIVIDUAL),
        poster_style=CollectionPosterStyle.INDIVIDUAL,
    )
    db_session.add(row)
    await db_session.commit()
    await _choose(db_session, CollectionPosterStyle.MATTE)

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        entry = json.loads(archive.read("data/collections/tmdb-10.json"))

    assert (
        entry["poster_url_individual"],
        entry["poster_url_matte"],
        entry["poster_url_overlay"],
    ) == (INDIVIDUAL, None, None)
