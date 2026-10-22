"""A single real connection remains available while artwork providers wait."""

lazy import asyncio
lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlalchemy.ext.asyncio import create_async_engine

lazy from overture.config import Settings
lazy from overture.db import metadata
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database, configure_sqlite
lazy from overture.domain import ArtType, MediaType, ServerType, TmdbLanguageFilter
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.service import ArtService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.server_identity import resolve_server_item_id
lazy from overture.services.storage.assets import AssetStorage
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    NoopTmdb,
    RecordingPublisher,
    unused,
)


@pytest.mark.parametrize("art_type", [ArtType.POSTER, ArtType.SEASON_POSTER])
@pytest.mark.parametrize("discover", [False, True])
async def test_art_sources_release_connection_during_discovery_and_candidates(
    tmp_path: Path,
    app_config: Settings,
    art_type: ArtType,
    discover: bool,
) -> None:
    engine = configure_sqlite(
        create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'single.db'}",
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.5,
        )
    )
    database = Database("", engine=engine)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    app_config.TMDB_API_KEY = SecretStr("test-key")
    discovery_started, discovery_release = asyncio.Event(), asyncio.Event()
    tmdb_started, server_started, candidates_release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    class Provider:
        server_type = ServerType.PLEX

        async def find_item_id(self, item: MediaItem) -> str:
            assert item.tmdb_id == 42
            discovery_started.set()
            await discovery_release.wait()
            return "parent"

        async def build_item_link(self, server_item_id: str) -> str:
            return f"https://server.test/{server_item_id}"

        async def find_season_id(self, server_item_id: str, season_num: int) -> str:
            assert (server_item_id, season_num) == ("parent", 0)
            return "season"

        async def get_art_candidates(
            self, server_id: str, art_type: ArtType
        ) -> list[Any]:
            assert server_id == ("season" if art_type.owned_by_season else "parent")
            server_started.set()
            await candidates_release.wait()
            return []

    class Tmdb(NoopTmdb):
        @override
        async def art_candidates(
            self,
            media_type: MediaType,
            tmdb_id: int,
            art_type: ArtType,
            *,
            season_num: int | None = None,
            language_filter: TmdbLanguageFilter = TmdbLanguageFilter.EN_NULL,
        ) -> list[Any]:
            assert tmdb_id == 42
            assert season_num == (0 if art_type.owned_by_season else None)
            tmdb_started.set()
            await candidates_release.wait()
            return []

    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                title="Movie",
                media_type=MediaType.SHOW
                if art_type.owned_by_season
                else MediaType.MOVIE,
                tmdb_id=42,
                server_item_id=None if discover else "parent",
            )
        )
        if art_type.owned_by_season:
            session.add(
                Season(
                    id=2,
                    media_item_id=1,
                    season_num=0,
                    server_item_id=None if discover else "season",
                )
            )
    registry = NoopProviderRegistry(Provider())
    service = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=unused(ArtMatcher),
        downloads=unused(DownloadService),
        publisher=RecordingPublisher(),
        provider_registry=registry,
        candidates=ArtCandidates(
            database=database,
            provider_registry=registry,
            tmdb_client=Tmdb(),
            app_config=app_config,
        ),
        image_clients=unused(ProxyClientManager),
    )

    async def unrelated_write() -> None:
        async with database.write_session() as session:
            item = await session.get(MediaItem, 1)
            assert item is not None
            item.monitored = False

    task = asyncio.create_task(
        service.get_sources(1, art_type, 2 if art_type.owned_by_season else None)
    )
    try:
        if discover:
            await asyncio.wait_for(discovery_started.wait(), 2)
            await asyncio.wait_for(unrelated_write(), 1)
            discovery_release.set()
        await asyncio.wait_for(
            asyncio.gather(tmdb_started.wait(), server_started.wait()), 2
        )
        await asyncio.wait_for(unrelated_write(), 1)
        candidates_release.set()
        await asyncio.wait_for(task, 2)
        async with database.read_session() as session:
            item = await session.get(MediaItem, 1)
            assert item is not None
            assert item.server_item_id == "parent"
            assert item.monitored is False
            if art_type.owned_by_season:
                season = await session.get(Season, 2)
                assert season is not None
                assert season.server_item_id == "season"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


@pytest.mark.parametrize("change", ["delete", "new_identity", "unrelated"])
async def test_discovery_rereads_before_persisting(
    app_config: Settings, database: Database, change: str
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaItem(id=1, title="Movie", media_type=MediaType.MOVIE, tmdb_id=42)
        )

    class Provider:
        async def find_item_id(self, item: MediaItem) -> str:
            # A concurrent application writer commits while the provider is awaited.
            async with database.write_session() as session:
                current = await session.get(MediaItem, 1)
                assert current is not None
                if change == "delete":
                    await session.delete(current)
                elif change == "new_identity":
                    current.server_item_id = "newer"
                else:
                    current.title = "Edited while discovering"
            return "discovered"

        async def build_item_link(self, server_item_id: str) -> str:
            return f"https://server.test/{server_item_id}"

    result = await asyncio.wait_for(
        resolve_server_item_id(
            1,
            ArtType.POSTER,
            None,
            database=database,
            provider_registry=NoopProviderRegistry(Provider()),
        ),
        2,
    )
    assert (
        result
        == {"delete": None, "new_identity": "newer", "unrelated": "discovered"}[change]
    )
    async with database.read_session() as session:
        item = await session.get(MediaItem, 1)
        if change == "delete":
            assert item is None
        else:
            assert item is not None
            assert item.server_item_id == result
            if change == "unrelated":
                assert item.title == "Edited while discovering"
