"""Test AUTH_MODE settings, startup warning, and route behavior across modes."""

lazy import logging
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import httpx2
lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient
lazy from pydantic import SecretStr, ValidationError
lazy from starlette.websockets import WebSocket, WebSocketDisconnect

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.dependencies import get_auth
lazy from overture.main import create_app, websocket_endpoint
lazy from overture.runtime import RuntimeServices, build_runtime
lazy from overture.schemas.auth import LoginRequest
lazy from overture.services.auth import AuthService
lazy from overture.services.oidc import OIDCService
lazy from overture.utils.errors import PublicServiceError
lazy from tests.oidc_provider import TestOIDCProvider


async def _async_noop(*_args: object, **_kwargs: object) -> None:
    pass


def _empty_lifecycle(_self: RuntimeServices) -> tuple[()]:
    return ()


def make_oidc_config(app_config: Settings, **overrides: Any) -> Settings:
    values = app_config.model_dump()
    values.update(
        {
            "AUTH_MODE": "oidc",
            "APP_URL": "https://overture.example.test",
            "OIDC_ISSUER_URL": "https://idp.example.test",
            "OIDC_CLIENT_ID": "overture",
            "OIDC_CLIENT_SECRET": "test-client-secret",
        }
    )
    values.update(overrides)
    return Settings.model_validate(values)


def test_auth_mode_defaults_to_password(app_config: Settings) -> None:
    assert app_config.AUTH_MODE == "password"
    assert app_config.password_enabled is True
    assert app_config.oidc_enabled is False


@pytest.mark.parametrize("mode", ["PASSWORD", "Password", "password"])
def test_auth_mode_normalises_case(app_config: Settings, mode: str) -> None:
    config = Settings.model_validate(app_config.model_dump() | {"AUTH_MODE": mode})
    assert config.AUTH_MODE == "password"


def test_auth_mode_rejects_unknown_mode(app_config: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(app_config.model_dump() | {"AUTH_MODE": "invalid"})


def test_none_mode_configuration_requires_no_secrets(app_config: Settings) -> None:
    values = app_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    values["AUTH_MODE"] = "none"
    config = Settings.model_validate(values)
    assert config.AUTH_MODE == "none"
    assert config.password_enabled is False
    assert config.oidc_enabled is False


def test_none_mode_allows_auto_login(app_config: Settings) -> None:
    values = app_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    values.update({"AUTH_MODE": "none", "OIDC_AUTO_LOGIN": True})
    config = Settings.model_validate(values)
    assert config.AUTH_MODE == "none"
    assert config.OIDC_AUTO_LOGIN is True


def test_password_mode_rejects_auto_login(app_config: Settings) -> None:
    values = app_config.model_dump()
    values.update({"AUTH_MODE": "password", "OIDC_AUTO_LOGIN": True})
    with pytest.raises(
        ValidationError, match="OIDC_AUTO_LOGIN requires OIDC configuration"
    ):
        Settings.model_validate(values)


def test_both_mode_supports_auto_login(app_config: Settings) -> None:
    config = make_oidc_config(app_config, AUTH_MODE="both", OIDC_AUTO_LOGIN=True)
    assert config.AUTH_MODE == "both"
    assert config.OIDC_AUTO_LOGIN is True


def test_password_mode_requires_password_hash(app_config: Settings) -> None:
    values = app_config.model_dump()
    values["AUTH_MODE"] = "password"
    values["APP_PASSWORD_HASH"] = ""
    with pytest.raises(
        ValidationError,
        match="APP_PASSWORD_HASH is required when password authentication is enabled",
    ):
        Settings.model_validate(values)


def test_oidc_mode_requires_oidc_credentials(app_config: Settings) -> None:
    values = app_config.model_dump()
    values["AUTH_MODE"] = "oidc"
    with pytest.raises(
        ValidationError,
        match=(
            "OIDC_ISSUER_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET "
            "are required when OIDC is enabled"
        ),
    ):
        Settings.model_validate(values)


def test_both_mode_requires_both_sets_of_credentials(app_config: Settings) -> None:
    # Missing OIDC credentials
    values = app_config.model_dump()
    values["AUTH_MODE"] = "both"
    with pytest.raises(
        ValidationError,
        match=(
            "OIDC_ISSUER_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET "
            "are required when OIDC is enabled"
        ),
    ):
        Settings.model_validate(values)

    # Missing password hash
    oidc_values = make_oidc_config(app_config, AUTH_MODE="both").model_dump()
    oidc_values["APP_PASSWORD_HASH"] = ""
    with pytest.raises(
        ValidationError,
        match="APP_PASSWORD_HASH is required when password authentication is enabled",
    ):
        Settings.model_validate(oidc_values)


async def test_none_mode_auth_service_methods(
    app_config: Settings, database: Database
) -> None:
    values = app_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    values["AUTH_MODE"] = "none"
    config = Settings.model_validate(values)
    service = AuthService(config, database)

    assert await service.token_expiry("any-token") is None
    assert await service.revoke("any-token") is None
    await service.require_token(None)
    await service.require_token("any-token")
    assert (await service.me_response(None)).authenticated is True
    assert (await service.me_response("any-token")).authenticated is True
    with pytest.raises(PublicServiceError) as err:
        await service.login(
            LoginRequest(password=SecretStr("test")),
            socket_ip="127.0.0.1",
            x_forwarded_for="",
        )
    assert err.value.status_code == 404
    assert err.value.message == "Password login is disabled"


async def test_oidc_mode_auth_service_disables_password_login(
    app_config: Settings, database: Database
) -> None:
    config = make_oidc_config(app_config, AUTH_MODE="oidc")
    service = AuthService(config, database)
    with pytest.raises(PublicServiceError) as err:
        await service.login(
            LoginRequest(password=SecretStr("test")),
            socket_ip="127.0.0.1",
            x_forwarded_for="",
        )
    assert err.value.status_code == 404
    assert err.value.message == "Password login is disabled"


async def test_none_mode_logs_startup_warning(
    app_config: Settings,
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    values = app_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    values["AUTH_MODE"] = "none"
    config = Settings.model_validate(values)
    monkeypatch.setattr(database, "initialize", _async_noop)
    monkeypatch.setattr(RuntimeServices, "_lifecycle", _empty_lifecycle)
    monkeypatch.setattr(RuntimeServices, "_log_connectivity", _async_noop)
    monkeypatch.setattr(RuntimeServices, "start_ping_loop", _async_noop, raising=False)
    runtime = build_runtime(app_settings=config, database=database, config_dir=tmp_path)
    monkeypatch.setattr(runtime.websockets, "start_ping_loop", _async_noop)

    with caplog.at_level(logging.WARNING):
        await runtime.start(app_version="1.0.0")
        try:
            warning_messages = [
                record.getMessage()
                for record in caplog.records
                if record.levelno == logging.WARNING
            ]
            warning = "\n".join(warning_messages)
            assert "Running with AUTH_MODE=none disables all authentication" in warning
        finally:
            await runtime.stop()


async def test_password_mode_does_not_log_none_warning(
    app_config: Settings,
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(database, "initialize", _async_noop)
    monkeypatch.setattr(RuntimeServices, "_lifecycle", _empty_lifecycle)
    monkeypatch.setattr(RuntimeServices, "_log_connectivity", _async_noop)
    runtime = build_runtime(
        app_settings=app_config, database=database, config_dir=tmp_path
    )
    monkeypatch.setattr(runtime.websockets, "start_ping_loop", _async_noop)

    with caplog.at_level(logging.WARNING):
        await runtime.start(app_version="1.0.0")
        try:
            warning_messages = [
                record.getMessage()
                for record in caplog.records
                if record.levelno == logging.WARNING
            ]
            warning = "\n".join(warning_messages)
            assert "disables all authentication" not in warning
        finally:
            await runtime.stop()


@pytest.mark.parametrize("mode", ["oidc", "both"])
async def test_startup_warning_not_logged_for_oidc_or_both(
    app_config: Settings,
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str,
) -> None:
    config = make_oidc_config(app_config, AUTH_MODE=mode)
    monkeypatch.setattr(database, "initialize", _async_noop)
    monkeypatch.setattr(RuntimeServices, "_lifecycle", _empty_lifecycle)
    monkeypatch.setattr(RuntimeServices, "_log_connectivity", _async_noop)
    runtime = build_runtime(app_settings=config, database=database, config_dir=tmp_path)
    monkeypatch.setattr(runtime.websockets, "start_ping_loop", _async_noop)

    with caplog.at_level(logging.WARNING):
        await runtime.start(app_version="1.0.0")
        try:
            warning_messages = [
                record.getMessage()
                for record in caplog.records
                if record.levelno == logging.WARNING
            ]
            warning = "\n".join(warning_messages)
            assert "disables all authentication" not in warning
        finally:
            await runtime.stop()


def test_none_mode_bypasses_auth_and_csrf(
    app_config: Settings, database: Database, tmp_path: Path
) -> None:
    values = app_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    values["AUTH_MODE"] = "none"
    config = Settings.model_validate(values)
    app = create_app(
        build_runtime(app_settings=config, database=database, config_dir=tmp_path)
    )

    client = TestClient(app)
    try:
        # Protected endpoints bypass auth
        settings_resp = client.get("/api/settings")
        assert settings_resp.status_code == 200

        # /api/auth/me reports authenticated
        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json() == {"authenticated": True}

        # /api/auth/config reports auth_mode none
        config_resp = client.get("/api/auth/config")
        assert config_resp.status_code == 200
        assert config_resp.json() == {
            "auth_mode": "none",
            "oidc_enabled": False,
            "display_name": "Sign in with SSO",
            "auto_login": False,
        }

        # Mutating requests bypass CSRF
        logout_resp = client.post("/api/auth/logout")
        assert logout_resp.status_code == 200

        sync_stop_resp = client.post("/api/sync/stop")
        assert sync_stop_resp.status_code == 200

        # Password login is disabled in none mode
        login_resp = client.post("/api/auth/login", json={"password": "any"})
        assert login_resp.status_code == 404

        # OIDC login and callback are disabled in none mode
        oidc_resp = client.get("/api/auth/oidc/login")
        assert oidc_resp.status_code == 404

        oidc_cb_resp = client.get("/api/auth/oidc/callback")
        assert oidc_cb_resp.status_code == 404
    finally:
        client.close()


async def test_none_mode_websocket_connects_without_cookies(
    app_config: Settings, database: Database, tmp_path: Path
) -> None:
    class MockClientConnection:
        def __init__(self) -> None:
            self.accepted = False
            self.cookies: dict[str, str] = {}
            self.headers = {"origin": "http://testserver", "host": "testserver"}
            self.url = type("Url", (), {"scheme": "ws"})()
            self.closed: tuple[int, str] | None = None

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int = 1000, reason: str = "") -> None:
            self.closed = (code, reason)

        async def receive_json(self) -> object:
            raise WebSocketDisconnect(code=1000)

    values = app_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    values["AUTH_MODE"] = "none"
    config = Settings.model_validate(values)
    runtime = build_runtime(app_settings=config, database=database, config_dir=tmp_path)
    client = MockClientConnection()
    await websocket_endpoint(cast("WebSocket", client), runtime)
    assert client.accepted is True
    assert client.closed is None


def test_both_mode_supports_both_password_and_oidc(
    client: TestClient,
    test_app: FastAPI,
    database: Database,
    app_config: Settings,
) -> None:
    provider = TestOIDCProvider()
    config = make_oidc_config(app_config, AUTH_MODE="both")

    def accept_password(_password: bytes, _hash: bytes) -> bool:
        return True

    auth = AuthService(config, database, password_verifier=accept_password)
    auth.oidc = OIDCService(config, transport=httpx2.MockTransport(provider.handle))
    test_app.dependency_overrides[get_auth] = lambda: auth
    client.base_url = httpx2.URL(config.APP_URL)
    try:
        # Public config indicates both mode
        cfg = client.get("/api/auth/config")
        assert cfg.json() == {
            "auth_mode": "both",
            "oidc_enabled": True,
            "display_name": "Sign in with SSO",
            "auto_login": False,
        }

        # Password login succeeds
        pw_res = client.post("/api/auth/login", json={"password": "correct"})
        assert pw_res.status_code == 200
        assert "overture_token" in client.cookies
        assert client.get("/api/auth/me").json() == {"authenticated": True}

        # Clear cookies
        client.cookies.clear()
        assert client.get("/api/auth/me").json() == {"authenticated": False}

        # OIDC login succeeds
        oidc_login = client.get(
            "/api/auth/oidc/login?return_to=/", follow_redirects=False
        )
        assert oidc_login.status_code == 302
        code, state = provider.authorize(oidc_login.headers["location"])
        callback = client.get(
            "/api/auth/oidc/callback",
            params={"code": code, "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert "overture_token" in client.cookies
        assert client.get("/api/auth/me").json() == {"authenticated": True}
    finally:
        test_app.dependency_overrides.pop(get_auth, None)
        auth.close()
