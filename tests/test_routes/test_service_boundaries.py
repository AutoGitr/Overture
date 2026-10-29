"""HTTP evidence for services bound to an application's database and collaborators."""

lazy from datetime import UTC, datetime
lazy from pathlib import Path
lazy from typing import override
lazy from zoneinfo import ZoneInfo

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot, write_art_slot
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetItem
lazy from overture.db.session import Database
lazy from overture.dependencies import get_library
lazy from overture.domain import ArtType, MediaType, ServerType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.jobs.gate import LibraryGate
lazy from overture.main import create_app
lazy from overture.schemas.art import ArtCandidate
lazy from overture.schemas.common import MonitoredResponse
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.library.service import LibraryService
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.public_dataset.service import PublicDatasetService
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.services.sync.engine import SyncEngine
lazy from overture.utils.http_security import CSRF_COOKIE, CSRF_HEADER
lazy from overture.utils.time import utc_now
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    NoopYoutube,
    RecordingPublisher,
    make_download_service,
    make_runtime,
    unused,
)


class Provider:
    server_type = ServerType.PLEX

    async def get_art_candidates(
        self, server_id: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        assert (server_id, art_type) == ("movie-1", ArtType.POSTER)
        return [
            ArtCandidate(url="https://images.test/poster.jpg", width=100, height=150)
        ]


async def test_http_services_use_bound_database_events_and_queue(
    tmp_path: Path,
    app_config: Settings,
    database: Database,
) -> None:
    events = RecordingPublisher()
    registry = NoopProviderRegistry(Provider())
    downloads = make_download_service(
        events,
        provider_registry=registry,
        asset_storage=AssetStorage(app_config=app_config),
        phash=unused(PhashService),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=NoopYoutube(),
        app_config=app_config,
        database=database,
    )
    dataset = PublicDatasetService(
        scheduler=SchedulerService(app_config=app_config),
        publisher=events,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    runtime = make_runtime(
        config_dir=tmp_path,
        app_config=app_config,
        database=database,
        events=events,
        provider_registry=registry,
        downloads=downloads,
        public_dataset=dataset,
    )
    async with database.write_session() as session:
        item = MediaItem(
            id=1,
            title="Bound movie",
            media_type=MediaType.MOVIE,
            tmdb_id=42,
            server_item_id="movie-1",
            folder_path="/media/Bound movie",
            monitored=True,
        )
        write_art_slot(item, ArtType.POSTER, url="https://images.test/old.jpg")
        session.add(item)
        session.add(
            MediaCollection(
                server_item_id="collection-1",
                media_type=MediaType.MOVIE,
                server_type=ServerType.PLEX,
                title="Collection",
                last_synced_at=utc_now(),
            )
        )
        session.add(
            PublicDatasetItem(
                media_type=MediaType.MOVIE,
                tmdb_id=42,
                title="Curated movie",
                poster_url="https://images.test/curated.jpg",
            )
        )

    app = create_app(runtime)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/art/1/poster/sources")).status_code == 401
        client.cookies.set("overture_token", (await runtime.auth.new_session()).token)
        assert (await client.patch("/api/library/items/1/monitored")).status_code == 403
        client.cookies.set(CSRF_COOKIE, "test-csrf")
        client.headers[CSRF_HEADER] = "test-csrf"
        sources = await client.get("/api/art/1/poster/sources")
        assert sources.status_code == 200
        assert (
            sources.json()["sources"]["plex"][0]["url"]
            == "https://images.test/poster.jpg"
        )
        assert (await client.get("/api/art/999/poster/sources")).status_code == 404
        assert (await client.get("/api/art/1/banner/sources")).status_code == 422
        cleared = await client.delete("/api/art/1/poster")
        assert cleared.json() == {"status": "cleared"}
        monitored = await client.patch(
            "/api/library/items/1/monitored", json={"monitored": False}
        )
        assert monitored.json() == {"monitored": False}
        queued = await client.put("/api/themes/1", json={"youtube_id": "abcdefghijk"})
        assert queued.status_code == 200
        queued_selection = queued.json()["selection"]
        assert queued_selection["status"] == "enqueued"
        duplicate = await client.put(
            "/api/themes/1", json={"youtube_id": "abcdefghijk"}
        )
        assert duplicate.json()["selection"] == {
            **queued_selection,
            "status": "existing",
        }
        # The seeded collection came from the server, so it waits to be taken over.
        collection = await client.patch(
            "/api/collections/1/monitored?media_type=movie",
            json={"monitored": False},
        )
        assert collection.status_code == 409
        record = await client.get("/api/public-dataset/items/1/record")
        assert record.status_code == 200
        assert record.json()["item"]["title"] == "Curated movie"
        missing_sources = await client.get("/api/public-dataset/items/999/sources")
        assert missing_sources.status_code == 200
        assert missing_sources.json() == {
            "found": False,
            "item": None,
            "seasons": [],
        }

    async with database.read_session() as session:
        saved = await session.get(MediaItem, 1)
        assert saved is not None
        assert saved.monitored is False
        assert read_art_slot(saved, ArtType.POSTER).url is None
        job = await session.get(DownloadJob, queued_selection["job_id"])
        assert job is not None
        assert job.media_item_id == 1
    updates = events.payloads("library.item.upserted")
    assert [update["source"] for update in updates] == [
        "art.clear",
        "library.monitored",
    ]
    assert updates[-1]["item"]["monitored"] is False
    assert updates[-1]["item"]["poster_url"] is None
    snapshots = await downloads.snapshot_events()
    assert [event.job.id for event in snapshots] == [queued_selection["job_id"]]


async def test_http_domain_dependency_can_be_substituted(
    tmp_path: Path, app_config: Settings, database: Database
) -> None:
    class Substitute(LibraryService):
        @override
        async def set_monitored(
            self, item_id: int, monitored: bool
        ) -> MonitoredResponse:
            assert (item_id, monitored) == (47, False)
            return MonitoredResponse(monitored=True)

    runtime = make_runtime(
        config_dir=tmp_path, app_config=app_config, database=database
    )
    substitute = Substitute(
        downloads=runtime.downloads,
        database=database,
        publisher=RecordingPublisher(),
        asset_storage=unused(AssetStorage),
        image_cache=unused(ImageCache),
        provider_registry=NoopProviderRegistry(),
        proxy_clients=unused(ProxyClientManager),
    )
    app = create_app(runtime)
    app.dependency_overrides[get_library] = lambda: substitute
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        cookies={
            "overture_token": (await runtime.auth.new_session()).token,
            CSRF_COOKIE: "test-csrf",
        },
        headers={CSRF_HEADER: "test-csrf"},
    ) as client:
        response = await client.patch(
            "/api/library/items/47/monitored", json={"monitored": False}
        )
    assert response.status_code == 200
    assert response.json() == {"monitored": True}


@pytest.mark.parametrize("timezone", ["UTC", "Europe/Stockholm"])
@pytest.mark.parametrize("month", [1, 7])
async def test_sync_http_timezone_matches_scheduler_in_winter_and_summer(
    tmp_path: Path,
    app_config: Settings,
    database: Database,
    timezone: str,
    month: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_config.TZ = timezone

    class FrozenDateTime:
        @classmethod
        def now(cls, _tz: object) -> datetime:
            return datetime(2026, month, 15, tzinfo=UTC)

    monkeypatch.setattr("overture.services.scheduler.datetime", FrozenDateTime)
    scheduler = SchedulerService(app_config=app_config)
    engine = SyncEngine(
        tmdb_client=unused(TMDBClient),
        config_dir=tmp_path,
        downloads=unused(DownloadService),
        provider_registry=NoopProviderRegistry(),
        scheduler=scheduler,
        publisher=RecordingPublisher(),
        library_gate=LibraryGate(),
        local_assets=unused(LocalAssets),
        app_config=app_config,
        database=database,
    )
    runtime = make_runtime(
        config_dir=tmp_path, app_config=app_config, database=database, sync=engine
    )
    app = create_app(runtime)
    body = {
        "name": "Nightly",
        "enabled": True,
        "cron_expression": "0 4 * * *",
        "config": {"mode": "full", "library_ids": ["movies"]},
    }
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        cookies={
            "overture_token": (await runtime.auth.new_session()).token,
            CSRF_COOKIE: "test-csrf",
        },
        headers={CSRF_HEADER: "test-csrf"},
    ) as client:
        created = await client.post("/api/sync/schedules", json=body)
        assert created.status_code == 201
        assert created.json()["timezone"] == timezone
        info = scheduler.job_info(
            f"saved_schedule:{created.json()['id']}", include_trigger=True
        )
        assert info.cron_expression == "0 4 * * *"
        response = await client.get("/api/sync/schedules")
        [listed] = response.json()
        displayed = datetime.fromisoformat(listed["next_run"]).astimezone(
            ZoneInfo(listed["timezone"])
        )
        assert displayed.strftime("%Y-%m-%d %H:%M") == f"2026-{month:02d}-15 04:00"
        assert (
            displayed.utcoffset()
            == datetime(2026, month, 15, 4, tzinfo=ZoneInfo(timezone)).utcoffset()
        )
