"""FastAPI application coverage using TestClient."""

lazy from collections import deque
lazy from collections.abc import AsyncIterator, Iterator
lazy from pathlib import Path
lazy from typing import cast

lazy import pytest
lazy from fastapi import APIRouter, FastAPI, WebSocket
lazy from fastapi.responses import StreamingResponse
lazy from fastapi.testclient import TestClient
lazy from pydantic import SecretStr
lazy from sqlalchemy.pool import QueuePool
lazy from sqlmodel import select
lazy from starlette.websockets import WebSocketDisconnect

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.dependencies import SessionDep
lazy from overture.main import APP_VERSION, create_app, websocket_endpoint
lazy from overture.passwords import hash_password
lazy from overture.utils.http_security import CSRF_COOKIE, CSRF_HEADER
lazy from overture.utils.security import REDACTED
lazy from overture.ws.connection_manager import ConnectionManager
lazy from tests.runtime_helpers import make_runtime


@pytest.fixture
def client(*, test_app: FastAPI) -> Iterator[TestClient]:
    test_client = TestClient(test_app)
    try:
        yield test_client
    finally:
        test_client.close()


def test_health_returns_public_status_and_request_id(client: TestClient) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "rid-health"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "rid-health"
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == APP_VERSION
    assert "python" in body
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    directives = response.headers["Content-Security-Policy"].split("; ")
    assert "font-src 'self'" in directives
    assert "style-src 'self' 'unsafe-inline'" in directives
    assert (
        "frame-src https://www.youtube-nocookie.com"
        in response.headers["Content-Security-Policy"]
    )


@pytest.mark.parametrize("query", ["", "?limit=1", "?limit=50"])
def test_theme_search_accepts_defaults_and_limit_boundaries(
    authenticated_client: TestClient, query: str
) -> None:
    response = authenticated_client.get(f"/api/themes/search{query}")
    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "video_ids=invalid"])
def test_theme_search_preserves_model_field_constraints(
    authenticated_client: TestClient, query: str
) -> None:
    response = authenticated_client.get(f"/api/themes/search?{query}")
    assert response.status_code == 422


@pytest.mark.parametrize("content", ["", "null", "{}"])
def test_bulk_stop_accepts_omitted_null_and_default_bodies(
    authenticated_client: TestClient, auth_headers: dict[str, str], content: str
) -> None:
    response = authenticated_client.post(
        "/api/bulk/assets/stop",
        content=content,
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_login_rejects_explicit_null_body(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        content="null",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_docs_and_openapi_require_authentication(
    client: TestClient, *, session_token: str
) -> None:
    assert client.get("/api/docs").status_code == 401
    assert client.get("/api/openapi.json").status_code == 401

    client.cookies.set("overture_token", session_token)

    docs_response = client.get("/api/docs")
    assert docs_response.status_code == 200
    assert "swagger-ui" in docs_response.text.lower()
    csp = docs_response.headers["Content-Security-Policy"]
    assert "https://cdn.jsdelivr.net" in csp

    openapi_response = client.get("/api/openapi.json")
    assert openapi_response.status_code == 200
    assert openapi_response.json()["info"]["title"] == "Overture"


def test_auth_me_reports_anonymous_and_cookie_authenticated_users(
    client: TestClient, *, session_token: str
) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False,
    }

    client.cookies.set("overture_token", session_token)
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
    }


def test_login_rejects_invalid_credentials_without_setting_cookie(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/auth/login",
        json={"password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert "overture_token" not in response.cookies


def test_validation_errors_redact_sensitive_body_inputs(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"password": {"raw": "secret"}},
    )

    assert response.status_code == 422
    password_errors = [
        error
        for error in response.json()["detail"]
        if error.get("loc") == ["body", "password"]
    ]
    assert password_errors
    assert password_errors[0]["input"] == REDACTED


def test_csrf_runs_before_authenticated_mutating_routes(client: TestClient) -> None:
    response = client.post(
        "/api/asset-manager/scan",
        headers={"X-Request-ID": "rid-csrf"},
        json={},
    )

    assert response.status_code == 403
    assert response.headers["X-Request-ID"] == "rid-csrf"
    assert response.json() == {"detail": "Invalid CSRF token"}


def test_mutating_route_with_valid_csrf_still_requires_auth(
    client: TestClient,
) -> None:
    client.cookies.set(CSRF_COOKIE, "same-token")
    response = client.post(
        "/api/asset-manager/scan",
        headers={CSRF_HEADER: "same-token"},
        json={},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_websocket_without_auth_cookie_is_rejected(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws", headers={"Origin": "http://testserver"}),
    ):
        pass

    assert exc.value.code == 4001


def test_websocket_rejects_missing_and_cross_origin_requests(
    client: TestClient, *, session_token: str
) -> None:
    client.cookies.set("overture_token", session_token)

    with pytest.raises(WebSocketDisconnect) as missing, client.websocket_connect("/ws"):
        pass
    assert missing.value.code == 4003

    with (
        pytest.raises(WebSocketDisconnect) as cross_origin,
        client.websocket_connect("/ws", headers={"Origin": "https://attacker.example"}),
    ):
        pass
    assert cross_origin.value.code == 4003


def test_password_reset_rejects_old_session_for_http_and_websocket(
    tmp_path: Path, app_config: Settings, database: Database, session_token: str
) -> None:
    changed = app_config.model_copy(
        update={"APP_PASSWORD_HASH": SecretStr(hash_password("a new long password"))}
    )
    runtime = make_runtime(config_dir=tmp_path, app_config=changed, database=database)
    restarted = TestClient(create_app(runtime))
    try:
        restarted.cookies.set("overture_token", session_token)
        assert restarted.get("/api/auth/me").json() == {"authenticated": False}
        with (
            pytest.raises(WebSocketDisconnect) as rejected,
            restarted.websocket_connect("/ws", headers={"Origin": "http://testserver"}),
        ):
            pass
        assert rejected.value.code == 4001
    finally:
        restarted.close()


async def test_websocket_ignores_non_object_client_messages(
    tmp_path: Path, *, app_config: Settings, session_token: str, database: Database
) -> None:
    class MalformedClient:
        def __init__(self) -> None:
            self.accepted = False
            self.cookies = {"overture_token": session_token}
            self.headers = {"origin": "http://testserver", "host": "testserver"}
            self.url = type("Url", (), {"scheme": "ws"})()
            self.messages: deque[object] = deque([[]])

        async def accept(self) -> None:
            self.accepted = True

        async def receive_json(self) -> object:
            if self.messages:
                return self.messages.popleft()
            raise WebSocketDisconnect

    client = MalformedClient()
    manager = ConnectionManager()
    runtime = make_runtime(
        config_dir=tmp_path,
        websockets=manager,
        app_config=app_config,
        database=database,
    )

    await websocket_endpoint(cast("WebSocket", client), runtime)

    assert client.accepted is True
    assert manager.active_connections == 0


def test_provider_art_rejects_invalid_type(
    client: TestClient, *, session_token: str
) -> None:
    client.cookies.set("overture_token", session_token)

    unknown = client.get("/api/library/items/1/provider-art?type=thumb")
    season_slot = client.get("/api/library/items/1/provider-art?type=season_poster")

    assert unknown.status_code == 422
    assert season_slot.status_code == 400
    assert season_slot.json() == {"detail": "An item has no season artwork"}


def test_request_session_returns_its_connection_before_the_response_is_sent(
    client: TestClient, *, test_app: FastAPI, database: Database
) -> None:
    pool = database.engine.pool
    assert isinstance(pool, QueuePool)

    router = APIRouter()

    @router.get("/api/test-session-stream")
    async def stream(db: SessionDep) -> StreamingResponse:
        await db.exec(select(1))

        async def body() -> AsyncIterator[str]:
            yield str(pool.checkedout())

        return StreamingResponse(body())

    test_app.include_router(router)
    assert client.get("/api/test-session-stream").text == "0"


def test_image_routes_reject_an_unknown_size(
    client: TestClient, *, session_token: str
) -> None:
    client.cookies.set("overture_token", session_token)

    for path in (
        "/api/library/items/1/local-image/poster?size=huge",
        "/api/library/items/1/provider-art?size=huge",
        "/api/library/seasons/1/provider-art?size=huge",
        "/api/collections/1/image/poster?size=huge",
    ):
        assert client.get(path).status_code == 422, path
