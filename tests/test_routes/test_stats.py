"""Tests for the stats route."""

lazy from pathlib import Path

lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import (
    ContentFacts,
    Destination,
    confirm_delivery,
    record_content,
    select_theme,
    set_needed,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    DeliveryChannel,
    MediaType,
    ServerAsset,
    ServerType,
    ThemeIdSource,
)
lazy from overture.main import create_app
lazy from overture.schemas.stats import StatsResponse
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import shown_on_server, stored_collection
lazy from tests.factories import seed_asset, seed_theme
lazy from tests.runtime_helpers import NoopProviderRegistry, make_runtime


class FakePlex:
    """A media server with collections; stats read them from the last sync."""

    server_type = ServerType.PLEX


@pytest.fixture
def media_server() -> FakePlex | None:
    """No media server by default; tests parametrize this to provide one."""
    return None


@pytest.fixture
def test_app(
    app_config: Settings,
    database: Database,
    tmp_path: Path,
    media_server: FakePlex | None,
) -> FastAPI:
    return create_app(
        make_runtime(
            app_config=app_config,
            database=database,
            config_dir=tmp_path,
            provider_registry=NoopProviderRegistry(media_server),
        )
    )


def _stats(data: object) -> StatsResponse:
    """Read a stats response; its computed coverage figures are output only."""
    return StatsResponse.model_validate(data, extra="ignore")


def test_stats_unauthenticated_returns_401(client: TestClient) -> None:
    """Unauthenticated requests must be rejected."""
    response = client.get("/api/stats")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_stats_authenticated_returns_valid_schema(
    authenticated_client: TestClient,
) -> None:
    """Authenticated requests return a complete StatsResponse schema."""
    response = authenticated_client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    validated = _stats(data)

    assert validated.library.total_movies == 0
    assert validated.library.total_shows == 0
    assert validated.art.overall.local_files == 0
    assert validated.art.overall.matched_files == 0
    assert validated.themes.overall.local_files == 0
    assert validated.themes.overall.matched_files == 0
    assert validated.database.page_size > 0
    assert len(validated.database.tables) >= 10
    table_names = {t.table_name for t in validated.database.tables}
    assert "media_items" in table_names
    assert "seasons" in table_names
    assert {"assets", "asset_deliveries"} <= table_names
    assert "media_collections" in table_names
    # Without a media server there are no collections to count.
    assert validated.library.total_collections is None
    assert validated.library.monitored_collections is None
    assert validated.themes.collections is None


@pytest.mark.parametrize("media_server", [FakePlex()])
async def test_stats_with_seeded_data(
    authenticated_client: TestClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Seeded items and assets must be accurately counted and sized."""
    # Theme sizes are the recorded ones; stats never read the files.
    movie_folder = tmp_path / "Movie (2020)"
    theme_size = 36

    # Seed movies
    movie1 = MediaItem(
        media_type=MediaType.MOVIE,
        title="Movie One",
        year=2020,
        monitored=True,
        folder_path=str(movie_folder),
    )
    seed_theme(movie1, "abc123xyz", file_hash="theme-hash", file_size=theme_size)
    movie2 = MediaItem(
        media_type=MediaType.MOVIE,
        title="Movie Two",
        year=2022,
        monitored=False,
    )
    # OvertureDB says it has no theme: complete, but nothing was matched.
    set_needed(movie2, ServerAsset.THEME, False)
    # Seed show with 2 seasons
    show1 = MediaItem(
        media_type=MediaType.SHOW,
        title="Show One",
        year=2021,
        monitored=True,
    )
    db_session.add_all([movie1, movie2, show1])
    await db_session.commit()
    await db_session.refresh(movie1)
    await db_session.refresh(movie2)
    await db_session.refresh(show1)

    # Add artwork
    seed_asset(
        movie1,
        ArtType.POSTER,
        url="https://example.com/poster.jpg",
        file_hash="hash123",
        file_size=1000,
    )
    seed_asset(movie1, ArtType.BACKGROUND, file_hash="background-hash", file_size=2000)
    db_session.add(movie1)

    # Add seasons for show1
    season1 = Season(
        media_item_id=show1.id,
        season_num=1,
        title="Season 1",
        file_count=10,
    )
    season2 = Season(
        media_item_id=show1.id,
        season_num=2,
        title="Season 2",
        file_count=0,
    )
    db_session.add_all([season1, season2])
    await db_session.commit()
    await db_session.refresh(season1)
    await db_session.refresh(season2)

    # Season 1 has local poster (500 bytes)
    seed_asset(season1, ArtType.SEASON_POSTER, file_hash="season-hash", file_size=500)
    db_session.add(season1)
    await db_session.commit()

    # Seed a synced collection with the theme Overture stored
    coll1 = shown_on_server(
        stored_collection(
            server_item_id="coll-1",
            media_type=MediaType.MOVIE,
            monitored=True,
            last_synced_at=utc_now(),
        )
    )
    seed_asset(coll1, ArtType.POSTER, file_hash="collection-hash")
    select_theme(
        coll1,
        "coll_yt_123",
        source=ThemeIdSource.DOWNLOAD,
        title=None,
        duration=None,
    )
    record_content(coll1, ServerAsset.THEME, ContentFacts("youtube:coll_yt_123"))
    confirm_delivery(
        coll1,
        ServerAsset.THEME,
        Destination(1, "coll-1", DeliveryChannel.UPLOAD),
        ref="server_th_1",
    )
    db_session.add(coll1)
    await db_session.commit()

    # Query stats
    response = authenticated_client.get("/api/stats")
    assert response.status_code == 200
    stats = _stats(response.json())

    # Library checks
    assert stats.library.total_movies == 2
    assert stats.library.monitored_movies == 1
    assert stats.library.unmonitored_movies == 1
    assert stats.library.total_shows == 1
    assert stats.library.monitored_shows == 1
    assert stats.library.total_seasons == 2
    assert stats.library.seasons_with_episodes == 1
    assert stats.library.total_collections == 1
    assert stats.library.monitored_collections == 1

    # Artwork checks
    # Posters: total = 2 movies + 1 show = 3; local = 1; matched = 1
    assert stats.art.poster.total == 3
    assert stats.art.poster.local_files == 1
    assert stats.art.poster.local_percentage == 33.3
    assert stats.art.poster.matched_files == 1
    assert stats.art.poster.matched_percentage == 33.3
    assert stats.art.poster.total_size_bytes == 1000
    assert stats.art.poster_movies.local_files == 1
    assert stats.art.poster_movies.local_percentage == 50.0
    assert stats.art.poster_movies.matched_files == 1
    assert stats.art.poster_movies.matched_percentage == 50.0
    assert stats.art.poster_shows.local_files == 0
    assert stats.art.poster_shows.local_percentage == 0.0
    assert stats.art.poster_shows.matched_files == 0
    assert stats.art.poster_shows.matched_percentage == 0.0

    # Verify background slot stats: local = 1, matched = 0 (no url/hash)
    assert stats.art.background.total == 3
    assert stats.art.background.local_files == 1
    assert stats.art.background.local_percentage == 33.3
    assert stats.art.background.matched_files == 0
    assert stats.art.background.matched_percentage == 0.0
    assert stats.art.background.total_size_bytes == 2000

    # Verify season poster slot stats: local = 1, matched = 0
    assert stats.art.season_poster.total == 2
    assert stats.art.season_poster.local_files == 1
    assert stats.art.season_poster.local_percentage == 50.0
    assert stats.art.season_poster.matched_files == 0
    assert stats.art.season_poster.matched_percentage == 0.0
    assert stats.art.season_poster.total_size_bytes == 500

    # A collection has a poster and a background; its copy shows the poster.
    # Overture keeps the uploaded image in its image cache, not as a file here.
    collection_art = stats.art.collections
    assert collection_art is not None
    assert (collection_art.total, collection_art.local_files) == (2, 1)
    assert collection_art.total_size_bytes == 0

    # Verify overall artwork totals
    assert stats.art.overall.total == 10
    assert stats.art.overall.local_files == 4
    assert stats.art.overall.local_percentage == 40.0
    assert stats.art.overall.matched_files == 1
    assert stats.art.overall.matched_percentage == 10.0
    assert stats.art.overall.total_size_bytes == 3500

    # Theme checks
    assert stats.themes.movies.total == 2
    assert stats.themes.movies.local_files == 1
    assert stats.themes.movies.local_percentage == 50.0
    assert stats.themes.movies.matched_files == 1
    assert stats.themes.movies.matched_percentage == 50.0
    assert stats.themes.movies.total_size_bytes == theme_size

    assert stats.themes.shows.total == 1
    assert stats.themes.shows.local_files == 0
    assert stats.themes.shows.local_percentage == 0.0
    assert stats.themes.shows.matched_files == 0
    assert stats.themes.shows.matched_percentage == 0.0

    collections = stats.themes.collections
    assert collections is not None
    assert collections.total == 1
    assert collections.local_files == 1
    assert collections.local_percentage == 100.0
    assert collections.matched_files == 1
    assert collections.matched_percentage == 100.0

    assert stats.themes.overall.total == 4
    assert stats.themes.overall.local_files == 2
    assert stats.themes.overall.local_percentage == 50.0
    assert stats.themes.overall.matched_files == 2
    assert stats.themes.overall.matched_percentage == 50.0
    assert stats.themes.overall.total_size_bytes == theme_size

    # Storage summary
    assert stats.storage.artwork_size_bytes == 3500
    assert stats.storage.themes_size_bytes == theme_size
    assert stats.storage.image_cache_size_bytes == stats.image_cache.total_size_bytes
    assert stats.storage.total_footprint_bytes >= 3500 + theme_size
