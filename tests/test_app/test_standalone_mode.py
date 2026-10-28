"""MEDIA_SERVER=none runs Overture on OvertureDB and TMDB alone."""

lazy from pathlib import Path

lazy import pytest
lazy from fastapi.testclient import TestClient
lazy from pydantic import ValidationError

lazy from overture import runtime as runtime_module
lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import MediaServerState
lazy from overture.main import create_app
lazy from overture.runtime import build_runtime
lazy from overture.services.auth import AuthService
lazy from overture.utils.http_security import CSRF_COOKIE


def _settings(app_config: Settings, **values: object) -> Settings:
    fields = app_config.model_dump()
    fields.update(values)
    return Settings(**fields)


def test_none_needs_no_server_credentials_but_an_empty_value_is_an_error(
    app_config: Settings,
) -> None:
    standalone = _settings(
        app_config,
        MEDIA_SERVER="None",
        MEDIA_SERVER_URL="",
        MEDIA_SERVER_API_KEY="",
    )
    assert standalone.MEDIA_SERVER is None
    with pytest.raises(ValidationError, match="'none'"):
        _settings(app_config, MEDIA_SERVER="")
    with pytest.raises(ValidationError, match="MEDIA_SERVER_URL"):
        _settings(app_config, MEDIA_SERVER="plex", MEDIA_SERVER_URL="")


async def test_standalone_starts_and_refuses_server_bound_routes(
    app_config: Settings,
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def migrated(_before_upgrade: object) -> None:
        """The test database is created at head already."""

    config = _settings(
        app_config, MEDIA_SERVER="none", MEDIA_SERVER_URL="", MEDIA_SERVER_API_KEY=""
    )
    runtime = build_runtime(app_settings=config, database=database, config_dir=tmp_path)
    monkeypatch.setattr(database, "initialize", migrated)

    def accessible(*_args: object) -> bool:
        return True

    monkeypatch.setattr(runtime_module.os, "access", accessible)
    token = (
        await AuthService(app_config=config, database=database).new_session()
    ).token
    with TestClient(create_app(runtime)) as client:
        client.cookies.set("overture_token", token)
        client.cookies.set(CSRF_COOKIE, "csrf")
        settings = client.get("/api/settings")
        assert settings.status_code == 200
        assert settings.json()["media_server"] is None
        assert settings.json()["collections_supported"] is False
        for path in ("/api/sync/status", "/api/collections?media_type=movie"):
            refused = client.get(path)
            assert refused.status_code == 409
            assert refused.json()["detail"] == "No media server is configured"
        assert client.get("/api/public-dataset/status").status_code == 200
    assert runtime.provider_registry.health.current.state is MediaServerState.UNKNOWN
