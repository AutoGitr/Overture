"""Comparing local artwork files with the images a media server shows."""

lazy import io
lazy from collections.abc import AsyncIterator
lazy from concurrent.futures import ThreadPoolExecutor
lazy from pathlib import Path
lazy from typing import override

lazy import httpx2
lazy import pytest
lazy from PIL import Image

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from overture.schemas.server_audit import AuditStatus, ServerAuditResult
lazy from overture.services.art.phash import PhashService
lazy from overture.services.server_audit.compare import AuditContext, audit_target
lazy from overture.services.server_audit.work import AuditTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from tests.http_mock import mock_client_factory
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
)

SERVER_URL = "http://plex.local:32400/library/metadata/s1/thumb/1"


def _jpeg(*, flipped: bool = False) -> bytes:
    """A gradient poster; flipped, it looks nothing like the original."""
    image = Image.linear_gradient("L").convert("RGB")
    if flipped:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class ArtProvider:
    """A media server whose one item shows the poster at *url*."""

    def __init__(self, url: str | None) -> None:
        self.url = url

    async def find_item_id(self, item: MediaItem) -> str | None:
        return None

    def get_download_headers(self, url: str) -> dict[str, str]:
        return {"X-Plex-Token": "token"}


class ArtRegistry(NoopProviderRegistry):
    @override
    async def fetch_server_active_art_url(
        self, server_id: str, art_type: ArtType
    ) -> str | None:
        assert (server_id, art_type) == ("s1", ArtType.POSTER)
        return self.provider.url


@pytest.fixture
async def phash(app_config: Settings) -> AsyncIterator[PhashService]:
    service = PhashService(app_config=app_config, executor=ThreadPoolExecutor(1))
    yield service
    await service.close()


async def _audit(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService,
    local: bytes | None = None,
    server_url: str | None = SERVER_URL,
    served: httpx2.Response | None = None,
    server_item_id: str | None = "s1",
) -> tuple[ServerAuditResult, list[httpx2.Request]]:
    folder = tmp_path / "Alien (1979)"
    folder.mkdir()
    if local is not None:
        (folder / "poster.jpg").write_bytes(local)
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Alien",
                year=1979,
                folder_path=str(folder),
                server_item_id=server_item_id,
            )
        )
    factory, transport = mock_client_factory(
        lambda _request: served or httpx2.Response(404)
    )
    context = AuditContext(
        provider_registry=ArtRegistry(ArtProvider(server_url)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        image_clients=StaticImageClients(factory()),
        app_config=app_config,
        database=database,
        config_dir=tmp_path / "config",
    )
    _, [result] = await audit_target(AuditTarget(1, ArtType.POSTER), context=context)
    return result, transport.requests


def _image(data: bytes) -> httpx2.Response:
    return httpx2.Response(200, content=data, headers={"Content-Type": "image/jpeg"})


async def test_the_same_image_on_the_server_is_a_visual_match(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result, requests = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg(),
        served=_image(_jpeg()),
    )

    assert (result.status, result.reason, result.hamming) == (
        AuditStatus.PHASH_MATCH,
        "d=0 visual match",
        0,
    )
    assert result.title == "Alien"
    assert result.server_image_present
    assert result.local_path == str(tmp_path / "Alien (1979)" / "poster.jpg")
    assert [request.headers["X-Plex-Token"] for request in requests] == ["token"]


async def test_a_different_image_on_the_server_reports_its_distance(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result, _ = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg(),
        served=_image(_jpeg(flipped=True)),
    )

    assert result.status is AuditStatus.PHASH_MISMATCH
    assert result.hamming is not None
    assert result.hamming > 0
    assert result.reason == f"d={result.hamming}"


@pytest.mark.parametrize(
    ("has_local", "server_item_id", "server_url", "status", "reason"),
    [
        (
            False,
            "s1",
            SERVER_URL,
            AuditStatus.LOCAL_MISSING,
            "Local art file is missing",
        ),
        (
            True,
            None,
            SERVER_URL,
            AuditStatus.UNRESOLVED_SERVER_ID,
            "Could not resolve media-server item ID",
        ),
        (
            True,
            "s1",
            None,
            AuditStatus.SERVER_MISSING,
            "Media server has no active image for this art type",
        ),
    ],
)
async def test_an_image_that_cannot_be_compared_says_why(
    tmp_path: Path,
    has_local: bool,
    server_item_id: str | None,
    server_url: str | None,
    status: AuditStatus,
    reason: str,
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService,
) -> None:
    result, requests = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg() if has_local else None,
        server_item_id=server_item_id,
        server_url=server_url,
    )

    assert (result.status, result.reason) == (status, reason)
    assert requests == []


async def test_a_server_image_that_fails_to_download_is_an_error(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result, _ = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg(),
        served=httpx2.Response(503),
    )

    assert result.status is AuditStatus.ERROR
    assert result.reason
    assert result.server_image_present


async def test_an_item_gone_from_the_library_is_an_error(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    context = AuditContext(
        provider_registry=ArtRegistry(ArtProvider(SERVER_URL)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        image_clients=StaticImageClients(),
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )

    _, [result] = await audit_target(AuditTarget(404, ArtType.POSTER), context=context)

    assert (result.status, result.reason) == (AuditStatus.ERROR, "Item not found")
