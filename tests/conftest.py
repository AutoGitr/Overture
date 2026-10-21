"""Shared backend test fixtures.

The suite sets required environment defaults before application imports so
tests never depend on a local .env, real media-server credentials, or /config.
"""

lazy import asyncio
lazy import os
lazy from collections import deque
lazy from datetime import UTC, datetime
lazy from typing import Any
lazy from urllib.parse import urlsplit

os.environ.setdefault(
    "APP_PASSWORD_HASH",
    "$argon2id$v=19$m=19456,t=2,p=1$Y96qqNb5fWisYsjxPJH7rw$tmT2xh96T8fz3H2p6jD3VzxKyFZzHeUFucJGxjvSlM0",
)
os.environ.setdefault("MEDIA_SERVER", "plex")
os.environ.setdefault("MEDIA_SERVER_URL", "http://127.0.0.1:32400")
os.environ.setdefault("MEDIA_SERVER_API_KEY", "x" * 32)

lazy from collections.abc import AsyncGenerator, Generator
lazy from pathlib import Path

lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient
lazy from httpx2 import ASGITransport, AsyncClient
lazy from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db import metadata
lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetItem
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database, as_writer, configure_sqlite
lazy from overture.dependencies import get_session
lazy from overture.domain import ArtType, MediaType, ServerType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.main import create_app
lazy from overture.runtime import build_runtime
lazy from overture.services.art.phash import PhashService
lazy from overture.services.auth import AuthService
lazy from overture.services.public_dataset.schema.contract import ART_HOSTS
lazy from overture.utils import art_urls
lazy from overture.utils.http_security import CSRF_COOKIE, CSRF_HEADER
lazy from tests.factories import (
    AppSettingsFactory,
    ArtSpec,
    DownloadJobFactory,
    MediaItemFactory,
    PublicDatasetItemFactory,
    ScheduleFactory,
    SeasonFactory,
)


@pytest.fixture
def app_config() -> Settings:
    """Fresh validated configuration, independent of the process environment."""
    values = {name: field.default for name, field in Settings.model_fields.items()}
    values.update(
        {
            "APP_PASSWORD_HASH": (
                "$argon2id$v=19$m=19456,t=2,p=1$Y96qqNb5fWisYsjxPJH7rw$tmT2xh96T8fz3H2p6jD3VzxKyFZzHeUFucJGxjvSlM0"
            ),
            "MEDIA_SERVER": "plex",
            "MEDIA_SERVER_URL": "http://127.0.0.1:32400",
            "MEDIA_SERVER_API_KEY": "x" * 32,
        }
    )
    return Settings(**values)


@pytest.fixture(autouse=True)
def _terminate_phash_pools(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Terminate the worker processes of every pHash service a test built.

    Tests build services inline and rarely close them. A process pool left to
    the garbage collector and interpreter exit can keep pytest waiting on a
    spawned worker after the last test.
    """
    services: list[PhashService] = []
    initialise = PhashService.__init__

    def tracked(self: PhashService, **kwargs: Any) -> None:
        initialise(self, **kwargs)
        services.append(self)

    monkeypatch.setattr(PhashService, "__init__", tracked)
    yield
    for service in services:
        service.shutdown()


@pytest.fixture
def public_art_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat the catalog's art hosts as public without resolving them for real."""
    is_private_url = art_urls.is_private_url

    async def public_art_host(
        url: str, *, dns_cache: dict[str, asyncio.Task[bool]] | None = None
    ) -> bool:
        return urlsplit(url).hostname not in ART_HOSTS and await is_private_url(
            url, dns_cache=dns_cache
        )

    monkeypatch.setattr(art_urls, "is_private_url", public_art_host)


@pytest.fixture
def auth_service(app_config: Settings, database: Database) -> AuthService:
    return AuthService(app_config, database)


@pytest.fixture
async def session_token(auth_service: AuthService) -> str:
    """Issue a real persisted session shared by sync and async route tests."""
    return (await auth_service.new_session()).token


@pytest.fixture
def test_app(app_config: Settings, database: Database, tmp_path: Path) -> FastAPI:
    return create_app(
        build_runtime(
            app_settings=app_config,
            database=database,
            config_dir=tmp_path,
        )
    )


@pytest.fixture
def client(test_app: FastAPI) -> Generator[TestClient]:
    test_client = TestClient(test_app)
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture
async def async_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
def csrf_pair() -> tuple[str, str]:
    return CSRF_HEADER, "csrf-test-token"


@pytest.fixture
def authenticated_client(
    client: TestClient, csrf_pair: tuple[str, str], session_token: str
) -> TestClient:
    _header, token = csrf_pair
    client.cookies.set("overture_token", session_token)
    client.cookies.set(CSRF_COOKIE, token)
    return client


@pytest.fixture
def auth_headers(csrf_pair: tuple[str, str]) -> dict[str, str]:
    header, token = csrf_pair
    return {header: token}


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    root.mkdir()
    return root


@pytest.fixture
async def isolated_engine(
    tmp_path: Path,
) -> AsyncGenerator[AsyncEngine]:
    db_path = tmp_path / "overture-test.db"
    # Pooled like production: a fresh aiosqlite connection per session costs a
    # thread, the pragmas and a schema read, which dominates many tests.
    engine = configure_sqlite(
        create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
    )

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def database(
    isolated_engine: AsyncEngine,
) -> Database:
    return Database("sqlite+aiosqlite://", engine=isolated_engine)


@pytest.fixture
def isolated_session_factory(
    isolated_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        as_writer(isolated_engine), class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def image_clients(
    app_config: Settings,
) -> AsyncGenerator[ProxyClientManager]:
    """Share and close the same bounded image-client pool production uses."""
    clients = ProxyClientManager(app_config=app_config)
    try:
        yield clients
    finally:
        await clients.close()


@pytest.fixture
async def db_session(
    isolated_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(
        as_writer(isolated_engine), expire_on_commit=False
    ) as session:
        yield session


@pytest.fixture
async def app_with_isolated_db(
    test_app: FastAPI,
    isolated_engine: AsyncEngine,
) -> AsyncGenerator[FastAPI]:
    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(
            as_writer(isolated_engine), expire_on_commit=False
        ) as session:
            yield session

    test_app.dependency_overrides[get_session] = override_get_session
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.pop(get_session, None)


def _apply_art[OwnerT: MediaItem | Season](
    owner: OwnerT, art: ArtSpec | None
) -> OwnerT:
    """Populate artwork slots on a freshly built model.

    Artwork lives in ``media_item_art`` / ``season_art`` rather than in
    prefixed columns, so tests declare it as
    ``art={"poster": {"url": ..., "width": ...}}`` using the slot field names
    (``url``, ``file_hash``, ``phash``, ``width``, ``height``,
    ``file_mtime_ns``, ``file_size``); a ``file_hash`` records a local file.
    """
    for art_type, fields in (art or {}).items():
        write_art_slot(owner, ArtType(art_type), **fields)
    return owner


@pytest.fixture
def media_item_factory() -> MediaItemFactory:
    def factory(
        art: ArtSpec | None = None,
        **overrides: Any,
    ) -> MediaItem:
        values: dict[str, Any] = {
            "id": 1,
            "media_type": MediaType.MOVIE,
            "title": "Test Movie",
            "year": 2024,
            "folder_path": "/media/Test Movie",
            "server_item_id": "100",
            "library_id": "1",
        }
        values.update(overrides)
        values["media_type"] = MediaType(values["media_type"])
        return _apply_art(MediaItem(**values), art)

    return factory


@pytest.fixture
def season_factory() -> SeasonFactory:
    def factory(
        art: ArtSpec | None = None,
        **overrides: Any,
    ) -> Season:
        values: dict[str, Any] = {
            "id": 10,
            "media_item_id": 1,
            "season_num": 1,
            "title": "Season 1",
        }
        values.update(overrides)
        return _apply_art(Season(**values), art)

    return factory


@pytest.fixture
def app_settings_factory() -> AppSettingsFactory:
    def factory(**overrides: Any) -> AppSettings:
        values: dict[str, Any] = {"id": 1}
        values.update(overrides)
        return AppSettings(**values)

    return factory


@pytest.fixture
def schedule_factory() -> ScheduleFactory:
    def factory(**overrides: Any) -> TaskSchedule:
        values: dict[str, Any] = {
            "task_name": "sync",
            "enabled": False,
            "cron_expression": "0 * * * *",
            "payload": {},
        }
        values.update(overrides)
        return TaskSchedule(**values)

    return factory


@pytest.fixture
def download_job_factory() -> DownloadJobFactory:
    def factory(**overrides: Any) -> DownloadJob:
        values: dict[str, Any] = {
            "media_item_id": 1,
            "job_type": "art",
            "target_url": "https://images.test/poster.jpg",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        values.update(overrides)
        return DownloadJob(**values)

    return factory


@pytest.fixture
def public_dataset_item_factory() -> PublicDatasetItemFactory:
    def factory(**overrides: Any) -> PublicDatasetItem:
        values: dict[str, Any] = {
            "id": 1,
            "media_type": MediaType.MOVIE,
            "tmdb_id": 123,
            "title": "Dataset Movie",
            "poster_url": "https://images.test/poster.jpg",
        }
        values.update(overrides)
        values["media_type"] = MediaType(values["media_type"])
        return PublicDatasetItem(**values)

    return factory


class FakeWebSocket:
    def __init__(self, incoming: list[dict[str, Any]] | None = None) -> None:
        self.accepted = False
        self.closed: tuple[int | None, str | None] | None = None
        self.sent: list[dict[str, Any]] = []
        self.sent_text: list[str] = []
        self._incoming = deque(incoming or [])

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed = (code, reason)

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def send_text(self, payload: str) -> None:
        self.sent_text.append(payload)

    async def receive_json(self) -> dict[str, Any]:
        if self._incoming:
            return self._incoming.popleft()
        await asyncio.Future()
        return {}


class FakeMediaServerProvider:
    """A reachable Jellyfin server that holds nothing."""

    server_type = ServerType.JELLYFIN

    async def test_connection(self) -> bool:
        return True


@pytest.fixture
def fake_websocket_factory() -> type[FakeWebSocket]:
    return FakeWebSocket


@pytest.fixture
def fake_media_provider() -> FakeMediaServerProvider:
    return FakeMediaServerProvider()
