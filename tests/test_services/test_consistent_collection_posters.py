"""OvertureDB's consistent collection posters, taken and contributed as chosen."""

lazy import json
lazy from pathlib import Path
lazy from zipfile import ZipFile

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import select_art
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.models.settings import SETTINGS_ROW_ID, AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, CollectionPosterStyle
lazy from overture.services.public_dataset.export import REPORT_NAME, export_selections
lazy from overture.services.public_dataset.index import PublicDatasetIndex
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.collection_helpers import stored_collection

OWN = "https://image.tmdb.org/t/p/original/own.jpg"
CONSISTENT = "https://theposterdb.com/api/assets/7"


async def _choose(session: AsyncSession, posters: CollectionPosterStyle) -> None:
    await session.merge(
        AppSettings(id=SETTINGS_ROW_ID, collection_overturedb_posters=posters)
    )
    await session.commit()


@pytest.mark.parametrize(
    ("posters", "expected"),
    [
        (CollectionPosterStyle.INDIVIDUAL, OWN),
        (CollectionPosterStyle.CONSISTENT, CONSISTENT),
    ],
)
async def test_a_collection_takes_the_poster_the_setting_chooses(
    db_session: AsyncSession,
    app_config: Settings,
    posters: CollectionPosterStyle,
    expected: str,
) -> None:
    await enable_public_dataset(db_session)
    await _choose(db_session, posters)
    db_session.add(
        PublicDatasetCollection(
            tmdb_id=10, title="Saga", poster_url=OWN, consistent_poster_url=CONSISTENT
        )
    )
    row = stored_collection(title="Saga", tmdb_collection_id=10)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, ["group", "rule"])

    index = await PublicDatasetIndex.build_collections(
        db_session, [row], app_config=app_config
    )

    assert index.collection_art(row, ArtType.POSTER).value == expected


async def test_a_group_chooses_its_collections_posters_over_the_global_choice(
    db_session: AsyncSession, app_config: Settings
) -> None:
    await enable_public_dataset(db_session)
    await _choose(db_session, CollectionPosterStyle.INDIVIDUAL)
    db_session.add(
        PublicDatasetCollection(
            tmdb_id=10, title="Saga", poster_url=OWN, consistent_poster_url=CONSISTENT
        )
    )
    row = stored_collection(title="Saga", tmdb_collection_id=10, group="Franchises")
    assert row.group is not None
    row.group.overturedb_posters = CollectionPosterStyle.CONSISTENT
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, ["group", "rule"])

    index = await PublicDatasetIndex.build_collections(
        db_session, [row], app_config=app_config
    )

    assert index.collection_art(row, ArtType.POSTER).value == CONSISTENT


async def test_a_consistent_poster_is_contributed_as_one_from_tmdb_or_theposterdb(
    db_session: AsyncSession, tmp_path: Path, database: Database
) -> None:
    await _choose(db_session, CollectionPosterStyle.CONSISTENT)
    for tmdb_id, url in (
        (10, CONSISTENT),
        (11, "https://assets.fanart.tv/fanart/a.jpg"),
    ):
        row = stored_collection(
            title=f"Saga {tmdb_id}",
            tmdb_collection_id=tmdb_id,
            youtube_id="dQw4w9WgXcQ",
            last_synced_at=utc_now(),
        )
        select_art(row, ArtType.POSTER, PublicArtUrl(url))
        db_session.add(row)
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        taken = json.loads(archive.read("data/collections/tmdb-10.json"))
        refused = json.loads(archive.read("data/collections/tmdb-11.json"))
        report = archive.read(REPORT_NAME).decode()

    assert (taken["poster_url"], taken["consistent_poster_url"]) == (None, CONSISTENT)
    # The theme still goes; only the poster a consistent one cannot be is left out.
    assert refused["consistent_poster_url"] is None
    assert refused["youtube_id_overturedb"] == "dQw4w9WgXcQ"
    assert "Saga 11: Poster: upload consistent posters to TMDB or ThePosterDB" in report
