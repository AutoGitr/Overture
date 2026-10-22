"""Shared bulk download queue delegation."""

lazy from typing import Any

lazy import pytest

lazy from overture import protocols
lazy from overture.config import Settings
lazy from overture.db.art_slots import select_art
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.services.art.phash import PhashService
lazy from overture.services.bulk_common import SelectionChangedError, queue_download
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_download_service,
    unused,
)


def _download_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    created: bool = True,
    app_config: Settings,
    database: Database,
) -> tuple[DownloadService, list[JobTarget]]:
    """Build a real DownloadService with queue_job stubbed out."""
    downloads = make_download_service(
        unused(protocols.EventPublisher),
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    calls: list[JobTarget] = []

    async def fake_queue_job(
        _session: Any, target: JobTarget, **_kwargs: Any
    ) -> tuple[str, bool]:
        calls.append(target)
        return "job-id", created

    monkeypatch.setattr(downloads, "queue_job", fake_queue_job)
    return downloads, calls


async def test_queue_download_returns_created_flag(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path="/media/movies/Movie",
            )
        )
    downloads, calls = _download_service(
        monkeypatch, created=True, app_config=app_config, database=database
    )

    created = await queue_download(
        JobTarget.art(1, ArtType.POSTER, "https://x/poster.jpg"),
        planned=None,
        downloads=downloads,
        on_queued=lambda _job_id: None,
        database=database,
    )

    assert created is True
    assert calls == [JobTarget.art(1, ArtType.POSTER, "https://x/poster.jpg")]


async def test_queue_download_returns_false_when_not_created(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.SHOW,
                title="Show",
                folder_path="/media/shows/Show",
            )
        )
        session.add(
            Season(
                id=3,
                media_item_id=1,
                season_num=1,
                title="Season 1",
            )
        )
    downloads, calls = _download_service(
        monkeypatch, created=False, app_config=app_config, database=database
    )

    created = await queue_download(
        JobTarget.art(1, ArtType.SEASON_POSTER, "https://x/season.jpg", season_id=3),
        planned=None,
        downloads=downloads,
        on_queued=lambda _job_id: None,
        database=database,
    )

    assert created is False
    assert calls[0].season_id == 3


async def test_queue_download_refuses_a_slot_whose_selection_changed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path="/media/movies/Movie",
            youtube_id="newer",
        )
        select_art(item, ArtType.POSTER, "https://x/newer.jpg")
        session.add(item)
    downloads, calls = _download_service(
        monkeypatch, app_config=app_config, database=database
    )

    for target in (
        JobTarget.art(1, ArtType.POSTER, "https://x/planned.jpg"),
        JobTarget.theme(1, "planned"),
        JobTarget.art(2, ArtType.POSTER, "https://x/gone.jpg"),
    ):
        with pytest.raises(SelectionChangedError):
            await queue_download(
                target,
                planned=None,
                downloads=downloads,
                on_queued=lambda _job_id: None,
                database=database,
            )

    assert calls == []
