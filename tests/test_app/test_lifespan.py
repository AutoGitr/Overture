"""Application runtime startup/shutdown sequencing."""

lazy import asyncio
lazy import logging
lazy import re
lazy from pathlib import Path

lazy import pytest
lazy from sqlalchemy.ext.asyncio import AsyncEngine

lazy from overture import runtime as runtime_module
lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.runtime import build_runtime
lazy from overture.schemas.settings import ConnectivityStatusResponse
lazy from tests.runtime_helpers import make_runtime


def _record_shutdown(
    runtime: runtime_module.RuntimeServices,
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
) -> None:
    """Probe real collaborators without weakening their construction contracts."""

    async def stop_background_jobs() -> None:
        events.append("background_jobs.stop")

    monkeypatch.setattr(runtime.background_jobs, "stop", stop_background_jobs)
    for name in ("provider_registry", "proxy_clients", "tmdb"):

        async def close(label: str = name) -> None:
            events.append(f"{label}.close")

        monkeypatch.setattr(getattr(runtime, name), "close", close)
    monkeypatch.setattr(
        runtime.phash, "shutdown", lambda: events.append("phash.shutdown")
    )

    engine_type = type(runtime.database.engine)
    real_dispose = engine_type.dispose

    async def dispose(engine: AsyncEngine, close: bool = True) -> None:
        events.append("engine.dispose")
        await real_dispose(engine, close)

    monkeypatch.setattr(engine_type, "dispose", dispose)


async def test_runtime_starts_and_stops_managers_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    events: list[str] = []
    connectivity_done = asyncio.Event()

    async def fake_init_db(_before_upgrade: object) -> None:
        events.append("db.init")

    async def fake_status(
        _provider_registry: ProviderRegistry,
        _tmdb_client: TMDBClient,
    ) -> ConnectivityStatusResponse:
        events.append("status.map")
        connectivity_done.set()
        return ConnectivityStatusResponse(media_server=True, tmdb=True)

    def always_accessible(*_args: object) -> bool:
        return True

    monkeypatch.setattr(runtime_module.os, "access", always_accessible)

    runtime = build_runtime(
        app_settings=app_config, database=database, config_dir=tmp_path / "config"
    )
    monkeypatch.setattr(database, "initialize", fake_init_db)
    runtime.connectivity_probe = fake_status
    _record_shutdown(runtime, monkeypatch, events)
    for field, label in (
        ("downloads", "download"),
        ("sync", "sync"),
        ("backups", "backup"),
        ("assets", "assets"),
        ("public_dataset", "public_dataset"),
    ):

        async def start(name: str = label) -> None:
            events.append(f"{name}.start")

        def stop(name: str = label) -> None:
            events.append(f"{name}.stop")

        monkeypatch.setattr(getattr(runtime, field), "start", start)
        monkeypatch.setattr(getattr(runtime, field), "stop", stop)

    async def ping() -> None:
        events.append("ping.start")
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.websockets, "start_ping_loop", ping)

    with caplog.at_level(logging.INFO, logger="overture.runtime"):
        await runtime.start(app_version="test")
    # The formatted startup line names the user the server runs as.
    assert re.search(
        r"^Overture test starting \(Python .+, UID -?\d+, GID -?\d+, timezone ",
        caplog.messages[0],
    )
    assert events[:6] == [
        "db.init",
        "download.start",
        "sync.start",
        "backup.start",
        "assets.start",
        "public_dataset.start",
    ]
    await asyncio.wait_for(connectivity_done.wait(), timeout=1)
    assert "status.map" in events

    await runtime.stop()

    assert events[-11:] == [
        "background_jobs.stop",
        "public_dataset.stop",
        "assets.stop",
        "backup.stop",
        "sync.stop",
        "download.stop",
        "provider_registry.close",
        "proxy_clients.close",
        "tmdb.close",
        "phash.shutdown",
        "engine.dispose",
    ]


async def test_runtime_rejects_a_config_path_that_is_not_a_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    config_path = tmp_path / "config"
    config_path.write_text("not a directory")

    runtime = make_runtime(
        config_dir=config_path, app_config=app_config, database=database
    )
    with pytest.raises(
        RuntimeError, match="Could not create persistent config directory"
    ):
        await runtime.start(app_version="test")


async def test_runtime_disposes_engine_when_database_initialization_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    events: list[str] = []

    async def fail_init_db(_before_upgrade: object) -> None:
        raise RuntimeError("database unavailable")

    runtime = build_runtime(
        app_settings=app_config, database=database, config_dir=tmp_path / "config"
    )
    monkeypatch.setattr(database, "initialize", fail_init_db)
    _record_shutdown(runtime, monkeypatch, events)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await runtime.start(app_version="test")
    await runtime.stop()

    assert events == [
        "background_jobs.stop",
        "provider_registry.close",
        "proxy_clients.close",
        "tmdb.close",
        "phash.shutdown",
        "engine.dispose",
    ]


def test_build_runtime_shares_one_instance_of_each_dependency(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    """Every runtime-owned service must reuse the container's own singletons.

    Guards against the factory quietly constructing a second copy of a shared
    service (an extra job registry, a second asset store), which would split
    state between collaborators that are meant to observe the same thing.
    """
    runtime = build_runtime(database=database, app_settings=app_config)

    # This test is about how build_runtime wires the concrete services, so it
    registry = runtime.provider_registry
    downloads = runtime.downloads
    art_matcher = runtime.art_matcher
    sync = runtime.sync
    backups = runtime.backups
    assets = runtime.assets

    assert sync.reconciler.publisher is runtime.events
    assert sync.reconciler.asset_storage is runtime.asset_storage

    art_handler = downloads.art_handler
    theme_handler = downloads.theme_handler
    assert art_handler.provider_registry is registry
    assert art_handler.asset_storage is runtime.asset_storage
    assert art_handler.phash is runtime.phash
    assert downloads.provider_registry is registry
    assert theme_handler.asset_storage is runtime.asset_storage
    assert theme_handler.youtube_resolver is runtime.youtube

    assert art_matcher.provider_registry is runtime.provider_registry
    assert art_matcher.phash is runtime.phash
    assert sync.provider_registry is runtime.provider_registry
    assert sync.downloads is runtime.downloads
    assert backups.scheduler is runtime.scheduler
    assert sync.schedules.scheduler is runtime.scheduler
    assert assets.schedules.scheduler is runtime.scheduler
    assert assets.downloads is runtime.downloads
    assert assets.art_matcher is runtime.art_matcher
    assert assets.youtube_resolver is runtime.youtube
    # One registry, not two: the schedule service and the WebSocket resync
    # layer must observe the same background jobs.
    assert assets.background_jobs is runtime.background_jobs


def test_build_runtime_uses_the_supplied_database_hooks(
    *, app_config: Settings, database: Database
) -> None:
    """The factory's only injection points are the database hooks."""
    runtime = build_runtime(database=database, app_settings=app_config)

    assert runtime.database is database
    assert runtime.database.engine is database.engine
    assert runtime.app_settings is app_config
