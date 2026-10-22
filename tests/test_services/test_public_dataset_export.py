"""Regression coverage for bulk contribution archives."""

lazy import json
lazy from pathlib import Path
lazy from zipfile import ZipFile

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from overture.services.public_dataset.export import (
    export_archive,
    export_selections,
)
lazy from overture.services.public_dataset.schema.contract import validate_entries
lazy from overture.utils.errors import PublicServiceError


async def test_export_reads_saved_season_art_and_omits_private_fields(
    db_session: AsyncSession,
    tmp_path: Path,
    database: Database,
) -> None:
    movie = MediaItem(
        media_type=MediaType.MOVIE,
        title="Movie",
        tmdb_id=12,
        youtube_id="abcdefghijk",
        folder_path="/private/movie",
    )
    show = MediaItem(media_type=MediaType.SHOW, title="Show", tmdb_id=99, tvdb_id=12)
    db_session.add_all([movie, show])
    await db_session.flush()
    assert show.id is not None
    season = Season(media_item_id=show.id, season_num=0)
    write_art_slot(
        season,
        ArtType.SEASON_POSTER,
        url="https://image.tmdb.org/t/p/original/test.jpg",
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
    invalid = MediaItem(
        media_type=MediaType.MOVIE,
        title="Missing ID",
        year=2001,
        youtube_id="abcdefghijk",
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
        MediaItem(
            media_type=MediaType.MOVIE, title=title, tmdb_id=1, youtube_id="abcdefghijk"
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
    write_art_slot(
        mixed,
        ArtType.POSTER,
        url="https://m.media-amazon.com/images/M/unallowed.jpg",
    )
    write_art_slot(
        mixed,
        ArtType.BACKGROUND,
        url="https://image.tmdb.org/t/p/original/valid_bg.jpg",
    )

    unsupported_only = MediaItem(
        media_type=MediaType.MOVIE,
        title="Amazon Only",
        tmdb_id=20,
    )
    write_art_slot(
        unsupported_only,
        ArtType.POSTER,
        url="https://m.media-amazon.com/images/M/unallowed2.jpg",
    )
    db_session.add_all([mixed, unsupported_only])
    await db_session.commit()

    with ZipFile(await export_selections(database, tmp_path)) as archive:
        assert set(archive.namelist()) == {
            "data/movies/tmdb-10.json",
        }
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
        MediaItem(
            media_type=MediaType.MOVIE, title=title, tmdb_id=1, youtube_id="abcdefghijk"
        )
        for title in ("One", "Two")
    ]
    db_session.add_all(items)
    await db_session.commit()
    with pytest.raises(PublicServiceError):
        await export_archive(database, config_dir)
    assert list(config_dir.iterdir()) == []
