"""Library service reads, writes and local images against an isolated database."""

lazy from datetime import UTC, datetime
lazy from pathlib import Path
lazy from typing import cast
lazy from unittest.mock import patch

lazy import pytest
lazy from fastapi import Response
lazy from fastapi.responses import FileResponse
lazy from PIL import Image
lazy from sqlmodel import text
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import (
    PublicDatasetItem,
    PublicDatasetSeason,
)
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, AspectRatioTolerance, ImageSize, MediaType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.media_servers.adapters import ProviderImageRequest, ServerSection
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.schemas.library import BulkItemOperation
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.library import service as library_module
lazy from overture.services.library.service import LibraryService
lazy from overture.services.storage.assets import AssetStorage, PathTraversalError
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.utils.assets import season_poster_candidates
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.file import compute_file_hash
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    database_for,
    make_local_assets,
    make_runtime,
    one_session,
    unused,
)


def _library_service(
    *, database: Database, app_config: Settings, config_dir: Path
) -> LibraryService:
    return make_runtime(
        config_dir=config_dir,
        database=database,
        app_config=app_config,
        asset_storage=AssetStorage(app_config=app_config),
    ).library


@pytest.mark.parametrize(
    ("tmdb_id", "tvdb_id", "imdb_id", "agreement"),
    [
        (10, 20, "tt0000030", "matching"),
        (11, 20, "tt0000030", "mismatching"),
        (10, 21, "tt0000030", "mismatching"),
        (10, 20, "tt0000031", "mismatching"),
        (10, 20, "", "matching"),
        (10, None, None, "matching"),
        (None, 20, None, "matching"),
        (None, None, "tt0000030", "matching"),
        (11, 21, "tt0000031", None),
        (None, None, None, None),
    ],
)
async def test_library_reports_whether_catalog_ids_agree(
    db_session: AsyncSession,
    tmp_path: Path,
    app_config: Settings,
    tmdb_id: int | None,
    tvdb_id: int | None,
    imdb_id: str | None,
    agreement: str | None,
) -> None:
    service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    db_session.add(
        MediaItem(
            id=1,
            media_type=MediaType.SHOW,
            title="Show",
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
        )
    )
    db_session.add(
        PublicDatasetItem(
            media_type=MediaType.SHOW,
            tmdb_id=10,
            tvdb_id=20,
            imdb_id="tt0000030",
        )
    )
    await db_session.commit()

    result = await service.list_items()
    detail = await service.get_item(1)
    assert result.items[0].public_dataset_ids == agreement
    assert detail.public_dataset_ids == agreement


@pytest.mark.parametrize(
    ("file_duration", "youtube_duration", "expected"),
    [(95, 120, 95), (None, 120, 120), (None, None, None)],
)
async def test_a_theme_is_as_long_as_its_local_file_else_its_video(
    db_session: AsyncSession,
    tmp_path: Path,
    app_config: Settings,
    file_duration: int | None,
    youtube_duration: int | None,
    expected: int | None,
) -> None:
    service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    db_session.add(
        MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            youtube_duration=youtube_duration,
            theme_file_duration=file_duration,
        )
    )
    await db_session.commit()

    assert (await service.get_item(1)).theme_duration == expected


async def test_library_reads_use_cached_theme_state_without_filesystem_access(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    db_session.add(
        MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(tmp_path),
            theme_file_hash="theme-hash",
        )
    )
    await db_session.commit()

    # Sync and asset operations own filesystem reconciliation. Even an offline
    # media mount must not delay or mutate the cached state on a library read.
    with patch.object(
        AssetStorage,
        "local_theme_path",
        side_effect=AssertionError("Library reads must not inspect media files"),
    ):
        result = await library_service.list_items()
        item = await library_service.get_item(1)

    assert [entry.id for entry in result.items] == [1]
    assert result.items[0].theme_file_hash == "theme-hash"
    assert item.theme_file_hash == "theme-hash"


async def test_list_items_reports_asset_state_and_filters_by_type(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    complete_folder = tmp_path / "Complete Movie"
    complete_folder.mkdir()
    (complete_folder / "theme.mp3").write_bytes(b"theme")
    complete = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Complete Movie",
        year=2026,
        tmdb_id=1,
        imdb_id="tt1",
        folder_path=str(complete_folder),
        server_item_id="plex-1",
        library_id="movies",
    )
    missing = MediaItem(id=2, media_type=MediaType.SHOW, title="Missing Show")
    missing_hash = MediaItem(
        id=4,
        media_type=MediaType.MOVIE,
        title="Missing Hash Movie",
        folder_path="/media/movies/Missing Hash Movie",
        server_item_id="plex-4",
    )
    sensitive_url = MediaItem(
        id=5,
        media_type=MediaType.MOVIE,
        title="Sensitive Url Movie",
        folder_path="/media/movies/Sensitive Url Movie",
        server_item_id="plex-5",
    )
    hidden = MediaItem(
        id=3,
        media_type=MediaType.MOVIE,
        title="Hidden Movie",
        server_removed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add(complete)
    db_session.add(missing)
    db_session.add(missing_hash)
    db_session.add(sensitive_url)
    db_session.add(hidden)
    await db_session.flush()

    write_art_slot(
        complete,
        ArtType.POSTER,
        url="https://img.test/poster.jpg",
        file_hash="poster-hash",
    )
    write_art_slot(
        complete,
        ArtType.BACKGROUND,
        url="https://img.test/background.jpg",
        file_hash="background-hash",
    )
    complete.youtube_id = "abcDEF123_4"
    complete.youtube_title = "Theme"
    complete.youtube_duration = 120
    complete.theme_file_hash = "theme-hash"

    # Links are saved but no local file was ever recorded for them.
    write_art_slot(
        missing_hash,
        ArtType.POSTER,
        url="https://img.test/missing-hash-poster.jpg",
    )
    write_art_slot(
        missing_hash,
        ArtType.BACKGROUND,
        url="https://img.test/missing-hash-background.jpg",
    )
    missing_hash.youtube_id = "missingHash1"
    missing_hash.youtube_title = "Selected Theme"
    missing_hash.youtube_duration = 90

    write_art_slot(
        sensitive_url,
        ArtType.POSTER,
        url="https://img.test/poster.jpg?X-Plex-Token=secret",
        file_hash="poster-hash",
    )
    write_art_slot(
        sensitive_url,
        ArtType.BACKGROUND,
        url="https://img.test/background.jpg?X-Plex-Token=secret",
        file_hash="background-hash",
    )

    db_session.add(
        PublicDatasetItem(
            id=1,
            media_type=MediaType.MOVIE,
            tmdb_id=1,
            poster_url="https://db.test/poster.jpg",
            background_url="https://db.test/background.jpg",
            youtube_id_overturedb="dbTheme1234",
        )
    )
    await db_session.commit()

    result = await library_service.list_items()
    assert [item.title for item in result.items] == [
        "Complete Movie",
        "Missing Hash Movie",
        "Sensitive Url Movie",
        "Missing Show",
    ]

    rows = {item.title: item for item in result.items}
    assert rows["Complete Movie"].art_status == "complete"
    assert rows["Complete Movie"].theme_status == "complete"
    assert rows["Complete Movie"].public_dataset_complete is True
    assert rows["Missing Hash Movie"].art_status == "partial"
    assert rows["Missing Hash Movie"].poster_status == "partial"
    assert rows["Missing Hash Movie"].theme_status == "partial"
    assert rows["Missing Show"].art_status == "missing"
    # URLs carrying a media-server token never reach the client, but the
    # saved link still counts towards completeness.
    assert rows["Sensitive Url Movie"].poster_url is None
    assert rows["Sensitive Url Movie"].poster_status == "complete"
    assert rows["Missing Show"].folder_path is None
    assert rows["Missing Show"].tmdb_id is None

    result = await library_service.list_items(media_type=MediaType.MOVIE)
    assert [item.title for item in result.items] == [
        "Complete Movie",
        "Missing Hash Movie",
        "Sensitive Url Movie",
    ]


async def test_list_items_reports_where_selected_artwork_comes_from(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    catalog_poster = "https://theposterdb.com/api/assets/1"
    item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie", tmdb_id=1)
    unlisted = MediaItem(id=2, media_type=MediaType.MOVIE, title="Unlisted")
    db_session.add_all([item, unlisted])
    await db_session.flush()
    write_art_slot(item, ArtType.POSTER, url=catalog_poster)
    write_art_slot(
        item,
        ArtType.BACKGROUND,
        url="https://image.tmdb.org/t/p/original/background.jpg",
    )
    write_art_slot(unlisted, ArtType.POSTER, url=catalog_poster)
    db_session.add(
        PublicDatasetItem(
            media_type=MediaType.MOVIE,
            tmdb_id=1,
            poster_url=catalog_poster,
            background_url="https://assets.fanart.tv/fanart/movies/1/other.jpg",
        )
    )
    await db_session.commit()

    rows = {row.title: row for row in (await library_service.list_items()).items}

    assert rows["Movie"].poster_source == "overturedb"
    assert rows["Movie"].background_source == "tmdb"
    # The same link counts as OvertureDB's only for the item it is listed for.
    assert rows["Unlisted"].poster_source == "tpdb"
    assert rows["Unlisted"].background_source is None


async def test_list_items_marks_tv_overturedb_complete_only_with_local_seasons(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    complete_show = MediaItem(
        id=10,
        media_type=MediaType.SHOW,
        title="Complete Show",
        tvdb_id=100,
        folder_path="/tv/Complete Show",
    )
    missing_season_show = MediaItem(
        id=11,
        media_type=MediaType.SHOW,
        title="Missing Season Show",
        tvdb_id=101,
        folder_path="/tv/Missing Season Show",
    )
    no_local_seasons_show = MediaItem(
        id=12,
        media_type=MediaType.SHOW,
        title="No Local Seasons Show",
        tvdb_id=102,
        folder_path="/tv/No Local Seasons Show",
    )
    db_session.add_all(
        [
            complete_show,
            missing_season_show,
            no_local_seasons_show,
            Season(
                id=100,
                media_item_id=10,
                season_num=1,
                file_count=5,
            ),
            Season(
                id=101,
                media_item_id=10,
                season_num=2,
                file_count=0,
            ),
            Season(
                id=102,
                media_item_id=11,
                season_num=1,
                file_count=5,
            ),
            PublicDatasetItem(
                id=1000,
                media_type=MediaType.SHOW,
                tvdb_id=100,
                poster_url="https://db.test/show-poster.jpg",
                background_url="https://db.test/show-bg.jpg",
                youtube_id_overturedb="showTheme01",
            ),
            PublicDatasetItem(
                id=1001,
                media_type=MediaType.SHOW,
                tvdb_id=101,
                poster_url="https://db.test/missing-poster.jpg",
                background_url="https://db.test/missing-bg.jpg",
                youtube_id_overturedb="showTheme02",
            ),
            PublicDatasetItem(
                id=1002,
                media_type=MediaType.SHOW,
                tvdb_id=102,
                poster_url="https://db.test/no-local-poster.jpg",
                background_url="https://db.test/no-local-bg.jpg",
                youtube_id_overturedb="showTheme03",
            ),
            PublicDatasetSeason(
                public_dataset_item_id=1000,
                season_num=1,
                poster_url="https://db.test/show-s1.jpg",
            ),
        ]
    )
    await db_session.commit()

    result = await library_service.list_items(media_type=MediaType.SHOW)
    status_by_title = {
        item.title: item.public_dataset_complete for item in result.items
    }

    assert status_by_title == {
        "Complete Show": True,
        "Missing Season Show": False,
        "No Local Seasons Show": False,
    }


async def test_set_monitored_sets_the_flag_and_rejects_unknown_items(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie", monitored=True)
    db_session.add(item)
    await db_session.commit()

    database = database_for(one_session(db_session))
    runtime = make_runtime(
        config_dir=tmp_path, app_config=app_config, database=database
    )

    assert (await runtime.library.set_monitored(1, False)).monitored is False
    assert (await runtime.library.set_monitored(1, False)).monitored is False
    assert (await runtime.library.set_monitored(1, True)).monitored is True

    with pytest.raises(PublicServiceError) as exc:
        await runtime.library.set_monitored(404, True)
    assert exc.value.status_code == 404


async def test_get_seasons_hides_empty_rows(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    db_session.add(
        MediaItem(id=1, media_type=MediaType.SHOW, title="Show", folder_path="/tv/Show")
    )
    db_session.add(Season(id=10, media_item_id=1, season_num=1, file_count=2))
    db_session.add(Season(id=11, media_item_id=1, season_num=2, file_count=0))
    await db_session.commit()

    seasons = await library_service.get_seasons(1)

    assert [season.season_num for season in seasons] == [1]
    assert seasons[0].file_count == 2


async def test_show_rows_report_season_poster_completeness(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    """Season-poster state is read from the artwork tables on every request."""
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    arted = MediaItem(id=1, media_type=MediaType.SHOW, title="Arted Show")
    unarted = MediaItem(id=2, media_type=MediaType.SHOW, title="Unarted Show")
    db_session.add_all([arted, unarted])
    await db_session.commit()

    for item in (arted, unarted):
        for art_type in (ArtType.POSTER, ArtType.BACKGROUND):
            write_art_slot(
                item,
                art_type,
                url=f"https://img.test/{art_type}.jpg",
                file_hash="h",
            )
        db_session.add(item)

    arted_season = Season(id=10, media_item_id=1, season_num=1, file_count=3)
    unarted_season = Season(id=11, media_item_id=2, season_num=1, file_count=3)
    db_session.add_all([arted_season, unarted_season])
    await db_session.commit()

    write_art_slot(
        arted_season,
        ArtType.SEASON_POSTER,
        url="https://img.test/s.jpg",
        file_hash="sh",
    )
    db_session.add(arted_season)
    await db_session.commit()

    rows = {item.title: item for item in (await library_service.list_items()).items}

    assert rows["Arted Show"].season_posters_status == "complete"
    assert rows["Arted Show"].art_status == "complete"
    assert rows["Unarted Show"].season_posters_status == "missing"
    assert rows["Unarted Show"].art_status == "partial"


@pytest.mark.parametrize(
    ("tolerance", "expected"),
    [
        (AspectRatioTolerance.STRICT, {"Square Poster", "Square Season"}),
        (AspectRatioTolerance.OFF, set[str]()),
    ],
)
async def test_items_report_incorrect_aspect_ratio_for_the_tolerance_setting(
    tmp_path: Path,
    db_session: AsyncSession,
    tolerance: AspectRatioTolerance,
    expected: set[str],
    *,
    app_config: Settings,
) -> None:
    """Posters, backgrounds and season posters share the backend ratio rule."""
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    db_session.add(AppSettings(id=1, aspect_ratio_tolerance=tolerance))
    good = MediaItem(id=1, media_type=MediaType.MOVIE, title="Good")
    square = MediaItem(id=2, media_type=MediaType.MOVIE, title="Square Poster")
    unmeasured = MediaItem(id=3, media_type=MediaType.MOVIE, title="Unmeasured")
    show = MediaItem(id=4, media_type=MediaType.SHOW, title="Square Season")
    db_session.add_all([good, square, unmeasured, show])
    season = Season(id=10, media_item_id=4, season_num=1, file_count=1)
    db_session.add(season)
    await db_session.commit()

    write_art_slot(good, ArtType.POSTER, width=1000, height=1500)
    write_art_slot(good, ArtType.BACKGROUND, width=1920, height=1080)
    write_art_slot(square, ArtType.POSTER, width=1000, height=1000)
    write_art_slot(unmeasured, ArtType.POSTER, url="https://img.test/p.jpg")
    write_art_slot(season, ArtType.SEASON_POSTER, width=500, height=500)
    db_session.add_all([good, square, unmeasured, season])
    await db_session.commit()

    result = await library_service.list_items()

    assert {
        item.title for item in result.items if item.has_incorrect_aspect_ratio
    } == expected


async def test_deleting_a_media_item_takes_its_seasons_and_artwork_with_it(
    db_session: AsyncSession,
) -> None:
    """Cascading foreign keys, not bookkeeping, keep the database consistent."""
    item = MediaItem(id=1, media_type=MediaType.SHOW, title="Doomed Show")
    db_session.add(item)
    await db_session.commit()

    write_art_slot(item, ArtType.POSTER, url="https://img.test/p.jpg")
    season = Season(id=10, media_item_id=1, season_num=1, file_count=1)
    db_session.add_all([item, season])
    await db_session.commit()
    write_art_slot(season, ArtType.SEASON_POSTER, url="https://img.test/s.jpg")
    db_session.add(season)
    await db_session.commit()

    await db_session.delete(item)
    await db_session.commit()

    table_queries = {
        "media_items": text("select count(*) from media_items"),
        "seasons": text("select count(*) from seasons"),
        "art_slots": text("select count(*) from art_slots"),
    }

    async def count(table: str) -> int:
        conn = await db_session.connection()
        result = await conn.execute(table_queries[table])
        return result.scalar() or 0

    assert await count("media_items") == 0
    assert await count("seasons") == 0
    assert await count("art_slots") == 0


async def test_image_cache_rejects_paths_outside_root_and_invalid_hashes(
    tmp_path: Path,
) -> None:
    cache = ImageCache(tmp_path / "cache" / "images")
    root = tmp_path / "library"
    sibling = tmp_path / "library-other"
    root.mkdir()
    sibling.mkdir()
    outside = sibling / "poster.jpg"
    _write_jpeg(outside, 100, 150)

    with pytest.raises(PathTraversalError):
        await cache.import_original(outside, root)

    assert await cache.original("../etc/passwd") is None
    assert await cache.original("not-a-blake3-hash") is None


def _write_jpeg(path: Path, width: int, height: int, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color).save(path, "JPEG")


def _record_file(owner: MediaItem | Season, art_type: ArtType, path: Path) -> str:
    """Record *path* as the slot's scanned file and return its BLAKE3 hash."""
    file_stat = path.stat()
    file_hash = compute_file_hash(path)
    assert file_hash is not None
    write_art_slot(
        owner,
        art_type,
        file_hash=file_hash,
        file_mtime_ns=file_stat.st_mtime_ns,
        file_size=file_stat.st_size,
    )
    return file_hash


async def _poster_movie(
    db_session: AsyncSession, folder: Path, *, width: int = 600
) -> str:
    poster = folder / "poster.jpg"
    _write_jpeg(poster, width, width * 3 // 2)
    movie = MediaItem(
        id=1, media_type=MediaType.MOVIE, title="Movie", folder_path=str(folder)
    )
    db_session.add(movie)
    await db_session.flush()
    file_hash = _record_file(movie, ArtType.POSTER, poster)
    await db_session.commit()
    return file_hash


def _response_image(response: Response) -> tuple[str | None, tuple[int, int]]:
    assert isinstance(response, FileResponse)
    with Image.open(response.path) as image:
        image.load()
        return image.format, image.size


async def test_local_image_display_is_downscaled_to_avif_and_served_from_cache(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    folder = tmp_path / "Movie"
    file_hash = await _poster_movie(db_session, folder, width=1000)

    response = await library_service.serve_local_image(
        item_id=1,
        art_type=ArtType.POSTER,
        size=ImageSize.DISPLAY,
        version=file_hash,
    )

    assert isinstance(response, FileResponse)
    assert response.media_type == "image/avif"
    assert Path(response.path) == (
        tmp_path / "cache" / "images" / "thumbs" / file_hash[:2] / f"{file_hash}.avif"
    )
    assert _response_image(response) == ("AVIF", (400, 600))
    assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"

    # Once cached, serving never touches the media folder again.
    (folder / "poster.jpg").unlink()
    cached_original = await library_service.serve_local_image(
        item_id=1,
        art_type=ArtType.POSTER,
        size=None,
        version=file_hash,
    )
    assert isinstance(cached_original, FileResponse)
    assert Path(cached_original.path) == (
        tmp_path / "cache" / "images" / "originals" / file_hash[:2] / f"{file_hash}.jpg"
    )


async def test_local_image_is_not_cached_for_another_version_or_a_changed_file(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    folder = tmp_path / "Movie"
    file_hash = await _poster_movie(db_session, folder)

    # Replaced outside Overture before the original was cached: the unverified
    # media-folder file must not be served under the old recorded hash.
    _write_jpeg(folder / "poster.jpg", 640, 960, color="blue")
    with pytest.raises(PublicServiceError) as exc_info:
        await library_service.serve_local_image(
            item_id=1,
            art_type=ArtType.POSTER,
            size=ImageSize.DISPLAY,
            version=file_hash,
        )
    assert exc_info.value.status_code == 404

    # Restore matching file and request with an older version query parameter.
    _write_jpeg(folder / "poster.jpg", 600, 900, color="red")
    stale_url = await library_service.serve_local_image(
        item_id=1,
        art_type=ArtType.POSTER,
        size=ImageSize.DISPLAY,
        version="old",
    )
    assert stale_url.headers["Cache-Control"] == "no-cache"


async def test_local_image_serves_cached_original_without_size_and_avif_thumb_with_size(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    file_hash = await _poster_movie(db_session, tmp_path / "Movie")

    original = await library_service.serve_local_image(
        item_id=1, art_type=ArtType.POSTER, size=None, version=file_hash
    )
    display = await library_service.serve_local_image(
        item_id=1,
        art_type=ArtType.POSTER,
        size=ImageSize.DISPLAY,
        version=file_hash,
    )

    assert isinstance(original, FileResponse)
    assert original.media_type == "image/jpeg"
    assert Path(original.path).is_relative_to(
        tmp_path / "cache" / "images" / "originals"
    )
    assert original.headers["Cache-Control"] == "private, max-age=31536000, immutable"

    assert isinstance(display, FileResponse)
    assert display.media_type == "image/avif"
    assert Path(display.path).is_relative_to(tmp_path / "cache" / "images" / "thumbs")
    assert display.headers["Cache-Control"] == "private, max-age=31536000, immutable"


async def test_local_image_rejects_season_artwork_for_an_item(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    folder = tmp_path / "Movie"
    await _poster_movie(db_session, folder)

    with pytest.raises(PublicServiceError) as exc_info:
        await library_service.serve_local_image(
            item_id=1,
            art_type=ArtType.SEASON_POSTER,
            size=None,
            version=None,
        )

    assert exc_info.value.status_code == 400


async def test_local_image_rejects_an_unreadable_file_when_sized(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    folder = tmp_path / "Movie"
    file_hash = await _poster_movie(db_session, folder)
    cached_original = (
        tmp_path / "cache" / "images" / "originals" / file_hash[:2] / f"{file_hash}.jpg"
    )
    cached_original.parent.mkdir(parents=True, exist_ok=True)
    cached_original.write_bytes(b"not an image")

    with pytest.raises(PublicServiceError) as exc_info:
        await library_service.serve_local_image(
            item_id=1,
            art_type=ArtType.POSTER,
            size=ImageSize.DISPLAY,
            version=file_hash,
        )

    assert exc_info.value.status_code == 422


async def test_local_season_poster_is_downscaled_and_cached_while_current(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    show_folder = tmp_path / "Show"
    season_folder = show_folder / "Season 1"
    season_folder.mkdir(parents=True)
    poster = season_folder / season_poster_candidates(app_config.MEDIA_SERVER, 1)[0]
    _write_jpeg(poster, 1000, 1500)
    db_session.add(
        MediaItem(
            id=1, media_type=MediaType.SHOW, title="Show", folder_path=str(show_folder)
        )
    )
    season = Season(
        id=10,
        media_item_id=1,
        season_num=1,
        file_count=1,
        folder_path=str(season_folder),
    )
    db_session.add(season)
    await db_session.flush()
    file_hash = _record_file(season, ArtType.SEASON_POSTER, poster)
    await db_session.commit()

    response = await library_service.serve_local_season_image(
        season_id=10, size=ImageSize.DISPLAY, version=file_hash
    )

    assert response.media_type == "image/avif"
    assert _response_image(response) == ("AVIF", (400, 600))
    assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"


async def test_refresh_imports_unchanged_recorded_file_when_cache_is_cold(
    tmp_path: Path,
    database: Database,
    *,
    app_config: Settings,
) -> None:
    folder = tmp_path / "Movie"
    poster = folder / "poster.jpg"
    _write_jpeg(poster, 600, 900)
    file_stat = poster.stat()
    file_hash = compute_file_hash(poster)
    assert file_hash is not None
    async with database.write_session() as session:
        item = MediaItem(
            id=1, media_type=MediaType.MOVIE, title="Movie", folder_path=str(folder)
        )
        write_art_slot(
            item,
            ArtType.POSTER,
            file_hash=file_hash,
            phash="0" * 16,
            width=600,
            height=900,
            file_mtime_ns=file_stat.st_mtime_ns,
            file_size=file_stat.st_size,
        )
        session.add(item)

    image_cache = ImageCache(tmp_path / "cache" / "images")
    local_assets = make_local_assets(
        app_config=app_config, database=database, image_cache=image_cache
    )
    assert not image_cache.has_original(file_hash)
    assert not image_cache.has_thumb(file_hash)

    changed = await local_assets.refresh(1, themes=False)

    assert changed is False
    assert image_cache.has_original(file_hash)
    assert image_cache.has_thumb(file_hash)


async def test_public_dataset_themerrdb_separation_and_completeness(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    library_service = _library_service(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
    )
    # Item with only themerrdb:
    # public_dataset_complete should be False, themerrdb True
    item1 = MediaItem(
        id=10, media_type=MediaType.MOVIE, title="Themerr Only Movie", tmdb_id=100
    )
    # Item with overturedb art and theme:
    # public_dataset_complete should be True, themerrdb False
    item2 = MediaItem(
        id=20, media_type=MediaType.MOVIE, title="Overture Complete Movie", tmdb_id=200
    )
    db_session.add_all([item1, item2])
    await db_session.flush()

    db_session.add_all(
        [
            PublicDatasetItem(
                media_type=MediaType.MOVIE,
                tmdb_id=100,
                poster_url="https://db.test/p1.jpg",
                background_url="https://db.test/b1.jpg",
                youtube_id_themerrdb="themerrYtId",
            ),
            PublicDatasetItem(
                media_type=MediaType.MOVIE,
                tmdb_id=200,
                poster_url="https://db.test/p2.jpg",
                background_url="https://db.test/b2.jpg",
                youtube_id_overturedb="overtureYtId",
            ),
        ]
    )
    await db_session.commit()

    result = await library_service.list_items(media_type=MediaType.MOVIE)
    by_title = {item.title: item for item in result.items}

    t1 = by_title["Themerr Only Movie"]
    assert t1.public_dataset_complete is False
    assert t1.public_dataset_themerrdb is True

    t2 = by_title["Overture Complete Movie"]
    assert t2.public_dataset_complete is True
    assert t2.public_dataset_themerrdb is False


async def test_bulk_set_monitored(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    runtime = make_runtime(
        config_dir=tmp_path,
        database=database_for(one_session(db_session)),
        app_config=app_config,
        asset_storage=AssetStorage(app_config=app_config),
    )
    item1 = MediaItem(id=31, media_type=MediaType.MOVIE, title="M1", monitored=True)
    item2 = MediaItem(id=32, media_type=MediaType.MOVIE, title="M2", monitored=True)
    item3 = MediaItem(id=33, media_type=MediaType.MOVIE, title="M3", monitored=False)
    db_session.add_all([item1, item2, item3])
    await db_session.commit()

    res = await runtime.library.bulk_operate_items(
        BulkItemOperation(item_ids=[31, 32], operation="unmonitor")
    )
    assert res.item_ids == [31, 32]

    reads = (await runtime.library.list_items(media_type=MediaType.MOVIE)).items
    by_id = {item.id: item.monitored for item in reads}
    assert by_id[31] is False
    assert by_id[32] is False
    assert by_id[33] is False


class ArtServer:
    """A media server that names its libraries and serves item art."""

    def __init__(self, sections: list[ServerSection] | None = None) -> None:
        self.sections = sections
        self.art_requests: list[tuple[str, ArtType, ImageSize | None]] = []

    async def get_sections(self) -> list[ServerSection]:
        if self.sections is None:
            raise MediaServerError("Media server unreachable")
        return self.sections

    async def build_provider_art_request(
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
    ) -> ProviderImageRequest:
        self.art_requests.append((server_item_id, art_type, size))
        return ProviderImageRequest(
            url=f"http://plex.local/{server_item_id}", headers={}
        )


@pytest.fixture
def proxied(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Answer every proxied image request; record the URLs proxied."""
    urls: list[str] = []

    async def proxy(request: ProviderImageRequest, **_kwargs: object) -> Response:
        urls.append(request.url)
        return Response(b"image", media_type="image/jpeg")

    monkeypatch.setattr(library_module, "proxy_provider_image", proxy)
    return urls


def _service(database: Database, server: ArtServer) -> LibraryService:
    return LibraryService(
        database=database,
        downloads=cast("DownloadService", None),
        publisher=NullEventPublisher(),
        asset_storage=cast("AssetStorage", None),
        image_cache=unused(ImageCache),
        provider_registry=NoopProviderRegistry(server),
        proxy_clients=cast("ProxyClientManager", None),
    )


async def _add_items(database: Database, *items: MediaItem) -> None:
    async with database.write_session() as session:
        session.add_all(items)


@pytest.mark.parametrize(
    ("sections", "listed"),
    [
        (
            [
                ServerSection("2", "Kids Movies", MediaType.MOVIE),
                ServerSection("1", "Classic Movies", MediaType.MOVIE),
            ],
            [("9", "9", 1), ("1", "Classic Movies", 2), ("2", "Kids Movies", 1)],
        ),
        (None, [("1", "1", 2), ("2", "2", 1), ("9", "9", 1)]),
    ],
)
async def test_libraries_are_named_by_the_media_server_while_it_answers(
    database: Database,
    sections: list[ServerSection] | None,
    listed: list[tuple[str, str, int]],
) -> None:
    await _add_items(
        database,
        MediaItem(id=1, media_type=MediaType.MOVIE, title="A", library_id="1"),
        MediaItem(id=2, media_type=MediaType.MOVIE, title="B", library_id="1"),
        MediaItem(id=3, media_type=MediaType.MOVIE, title="C", library_id="2"),
        MediaItem(id=4, media_type=MediaType.MOVIE, title="D", library_id="9"),
        MediaItem(id=5, media_type=MediaType.SHOW, title="E", library_id="5"),
        MediaItem(
            id=6,
            media_type=MediaType.MOVIE,
            title="Gone",
            library_id="1",
            server_removed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )

    libraries = await _service(database, ArtServer(sections)).get_libraries(
        MediaType.MOVIE
    )

    assert [(row.id, row.title, row.count) for row in libraries] == listed


async def test_item_provider_art_is_proxied_by_its_server_id(
    database: Database, proxied: list[str]
) -> None:
    server = ArtServer()
    await _add_items(
        database,
        MediaItem(id=1, media_type=MediaType.MOVIE, title="A", server_item_id="s1"),
        MediaItem(id=2, media_type=MediaType.MOVIE, title="B"),
    )
    library = _service(database, server)

    response = await library.proxy_item_provider_art(
        1, ArtType.POSTER, ImageSize.DISPLAY
    )

    assert response.body == b"image"
    assert server.art_requests == [("s1", ArtType.POSTER, ImageSize.DISPLAY)]
    assert proxied == ["http://plex.local/s1"]
    for item_id, art_type, status in (
        (1, ArtType.SEASON_POSTER, 400),
        (2, ArtType.POSTER, 404),
        (404, ArtType.POSTER, 404),
    ):
        with pytest.raises(PublicServiceError) as exc_info:
            await library.proxy_item_provider_art(item_id, art_type, None)
        assert exc_info.value.status_code == status


async def test_season_provider_art_is_proxied_by_the_season_server_id(
    database: Database, proxied: list[str]
) -> None:
    server = ArtServer()
    await _add_items(
        database,
        MediaItem(id=1, media_type=MediaType.SHOW, title="A", server_item_id="s1"),
    )
    async with database.write_session() as session:
        session.add(Season(id=10, media_item_id=1, season_num=2, server_item_id="s1-2"))
    library = _service(database, server)

    await library.proxy_season_provider_art(10, None)

    assert server.art_requests == [("s1-2", ArtType.SEASON_POSTER, None)]
    assert proxied == ["http://plex.local/s1-2"]
    with pytest.raises(PublicServiceError) as exc_info:
        await library.proxy_season_provider_art(11, None)
    assert exc_info.value.status_code == 404
