"""Authenticated library endpoints distinguish empty servers from failed requests."""

lazy from pathlib import Path

lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.media_servers.adapters import ServerSection
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.provider import JellyfinProvider
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_runtime,
)


@pytest.mark.parametrize("status", [200, 502, 503])
def test_library_http_error_contract(
    tmp_path: Path,
    status: int,
    authenticated_client: TestClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    provider = JellyfinProvider(app_config=app_config)

    async def sections() -> list[ServerSection]:
        if status != 200:
            raise MediaServerError("Media server is unavailable", status_code=status)
        return []

    monkeypatch.setattr(provider, "get_sections", sections)
    monkeypatch.setattr(
        test_app.state,
        "runtime",
        make_runtime(
            config_dir=tmp_path,
            provider_registry=NoopProviderRegistry(provider),
            app_config=app_config,
            database=database,
        ),
        raising=False,
    )
    response = authenticated_client.get("/api/media-server/libraries")
    assert response.status_code == status
    assert response.json() == (
        [] if status == 200 else {"detail": "Media server is unavailable"}
    )
