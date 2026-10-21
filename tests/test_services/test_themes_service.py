"""Theme search, selection and clearing through the owning service."""

lazy from collections.abc import Callable, Collection, Sequence
lazy from pathlib import Path
lazy from typing import Any, cast, override

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerAsset
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.schemas.themes import SearchRequest, ThemeSearchResult
lazy from overture.services.art.phash import PhashService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.errors import PublicServiceError
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    NoopYoutube,
    database_for,
    make_download_service,
    make_runtime,
    one_session,
    unused,
)


async def test_theme_search_filters_by_settings_duration(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    db_session.add(AppSettings(id=1, min_duration_seconds=30, max_duration_seconds=90))
    await db_session.commit()

    class FakeYoutube(NoopYoutube):
        @override
        async def search(
            self,
            query: str = "",
            limit: int = 10,
            video_ids: Sequence[str] | None = None,
        ) -> list[ThemeSearchResult]:
            return [
                ThemeSearchResult(id="short", title="Short", duration=10),
                ThemeSearchResult(id="ok", title="OK", duration=60),
                ThemeSearchResult(id="long", title="Long", duration=300),
            ]

    runtime = make_runtime(
        config_dir=tmp_path,
        youtube=FakeYoutube(),
        app_config=app_config,
        database=database,
    )

    result = await runtime.themes.search(
        SearchRequest(query="theme", limit=3),
    )

    assert [item.id for item in result.results] == ["ok"]
    assert result.results[0].duration == 60


async def test_theme_search_explicit_video_ids_bypass_duration_limits(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    db_session.add(AppSettings(id=1, min_duration_seconds=30, max_duration_seconds=90))
    await db_session.commit()

    class FakeYoutube(NoopYoutube):
        @override
        async def search(
            self,
            query: str = "",
            limit: int = 10,
            video_ids: Sequence[str] | None = None,
        ) -> list[ThemeSearchResult]:
            return [
                ThemeSearchResult(id="short_vid12", title="Short", duration=10),
                ThemeSearchResult(id="curated_sho", title="Curated", duration=15),
                ThemeSearchResult(id="ok_video_12", title="OK", duration=60),
            ]

    runtime = make_runtime(
        config_dir=tmp_path,
        youtube=FakeYoutube(),
        app_config=app_config,
        database=database,
    )

    result = await runtime.themes.search(
        SearchRequest(query="theme", limit=3, video_ids=["curated_sho"]),
    )

    assert [item.id for item in result.results] == ["curated_sho", "ok_video_12"]


async def test_theme_download_creates_job_and_reuses_existing(
    tmp_path: Path,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    database = database_for(one_session(db_session))
    downloads = make_download_service(
        make_runtime(
            config_dir=tmp_path, app_config=app_config, database=database
        ).events,
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        phash=unused(PhashService),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    runtime = make_runtime(
        config_dir=tmp_path,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )
    db_session.add(
        MediaItem(
            id=1, media_type=MediaType.MOVIE, title="Movie", folder_path="/media/Movie"
        )
    )
    await db_session.commit()

    first = await runtime.themes.select(1, "abcDEF123_4")
    second = await runtime.themes.select(1, "abcDEF123_4")

    assert first.selection.status == "enqueued"
    assert first.item.id == 1
    assert second.selection.job_id == first.selection.job_id
    assert second.selection.status == "existing"


async def test_theme_clear_forgets_the_selection_keeps_the_file_and_broadcasts(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
) -> None:
    refreshed: list[str] = []
    events: list[tuple[str, object]] = []

    class Provider:
        async def refresh_item(
            self, item_id: str, *, unlock: Collection[ServerAsset]
        ) -> None:
            refreshed.append(item_id)

    class RecordingPublisher:
        async def broadcast(
            self, event: str, payload: Any = None, **_kwargs: object
        ) -> None:
            events.append((event, payload))

        async def broadcast_built(
            self, builder: Callable[[], tuple[str, Any] | None]
        ) -> bool:
            built = builder()
            if built is None:
                return False
            event, payload = built
            events.append((event, payload))
            return True

    media_folder = tmp_path / "Movie"
    media_folder.mkdir()
    theme_path = media_folder / "theme.mp3"
    theme_path.write_bytes(b"theme")
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        folder_path=str(media_folder),
        server_item_id="plex-1",
    )
    db_session.add(item)
    await db_session.flush()
    item.youtube_id = "abcDEF123_4"
    item.youtube_title = "Theme"
    item.youtube_duration = 120
    item.theme_file_hash = "theme-hash"
    await db_session.commit()

    database = database_for(one_session(db_session))
    runtime = make_runtime(
        config_dir=tmp_path,
        events=RecordingPublisher(),
        provider_registry=NoopProviderRegistry(Provider()),
        app_config=app_config,
        database=database,
    )

    assert (await runtime.themes.clear(1)).status == "cleared"

    item = await db_session.get(MediaItem, 1)
    assert item is not None
    assert item.youtube_id is None
    assert item.youtube_title is None
    assert item.youtube_duration is None
    assert item.theme_provenance_cleared is True
    assert item.youtube_id_source is None
    assert item.theme_file_hash == "theme-hash"
    assert theme_path.read_bytes() == b"theme"
    # Only the selection changed; nothing on disk or on the server did.
    assert refreshed == []
    assert len(events) == 1
    assert events[0][0] == "library.item.upserted"
    raw_payload = events[0][1]
    assert isinstance(raw_payload, dict)
    payload = cast("dict[str, Any]", raw_payload)
    raw_item = payload["item"]
    assert isinstance(raw_item, dict)
    item_payload = cast("dict[str, Any]", raw_item)
    assert item_payload["id"] == 1
    assert payload["source"] == "themes.clear"


async def test_theme_download_missing_item_returns_404(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    database = database_for(one_session(db_session))
    runtime = make_runtime(
        config_dir=tmp_path, app_config=app_config, database=database
    )
    with pytest.raises(PublicServiceError) as exc:
        await runtime.themes.select(404, "abcDEF123_4")
    assert exc.value.status_code == 404
