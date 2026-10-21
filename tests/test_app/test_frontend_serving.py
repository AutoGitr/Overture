"""Integration tests for frontend serving and path-based routing fallback."""

lazy from collections.abc import Iterator
lazy from pathlib import Path

lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.main import create_app
lazy from overture.runtime import build_runtime
lazy from overture.utils.http_security import CSRF_COOKIE, CSRF_HEADER

HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@pytest.fixture
def temporary_frontend_dir(tmp_path: Path) -> Path:
    """Create a temporary frontend build directory with shell and assets."""
    dist = tmp_path / "frontend_dist"
    dist.mkdir(parents=True, exist_ok=True)

    (dist / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Overture</title></head>"
        "<body><div id='app'>Frontend Shell</div></body></html>",
    )

    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "bundle.js").write_text("console.log('overture-app');")
    (assets / "styles.css").write_text("body { margin: 0; }")
    (dist / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    return dist


@pytest.fixture
def frontend_app(
    temporary_frontend_dir: Path,
    app_config: Settings,
    database: Database,
    tmp_path: Path,
) -> FastAPI:
    """Create a FastAPI app instance with a mock frontend build directory."""
    runtime = build_runtime(
        app_settings=app_config,
        database=database,
        config_dir=tmp_path / "app_config",
    )
    return create_app(runtime, frontend_dir=temporary_frontend_dir)


@pytest.fixture
def client(frontend_app: FastAPI) -> Iterator[TestClient]:
    """TestClient configured with the frontend-enabled application."""
    test_client = TestClient(frontend_app)
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/movies",
        "/shows",
        "/movies/collections",
        "/shows/collections",
        "/movies/collections/1-action",
        "/shows/collections/2-drama",
        "/movies/42-the-matrix",
        "/shows/1-twin-peaks",
        "/movies/42-the-matrix/art",
        "/movies/42-the-matrix/art/poster",
        "/movies/42-the-matrix/art/background",
        "/movies/42-the-matrix/art/seasons",
        "/movies/42-the-matrix/themes",
        "/shows/1-twin-peaks/themes",
        "/shows/1-twin-peaks/art/seasons/1",
        "/movies/42-the-matrix/art/seasons/2",
    ],
)
def test_direct_navigation_and_head_requests_return_frontend_shell(
    client: TestClient, path: str
) -> None:
    """Direct browser navigation and HEAD requests to deep links return shell."""
    response = client.get(path, headers={"Accept": HTML_ACCEPT})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Frontend Shell" in response.text

    head_response = client.head(path, headers={"Accept": HTML_ACCEPT})
    assert head_response.status_code == 200
    assert "text/html" in head_response.headers["content-type"]
    assert head_response.text == ""


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api?probe=1",
        "/api/",
        "/API",
        "/API?probe=1",
        "/api/unknown",
        "/api/library/unknown-path",
        "/api/nonexistent",
        "/API/unknown",
        "/ws",
        "/ws?probe=1",
        "/ws/",
        "/WS",
        "/WS?probe=1",
        "/ws/events",
        "/ws/unknown/subpath",
    ],
)
def test_api_and_ws_namespaces_never_receive_html_fallback(
    client: TestClient, path: str
) -> None:
    """API and WS paths reject frontend fallback and return JSON 404."""
    response = client.get(
        path,
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}

    head_response = client.head(
        path,
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert head_response.status_code == 404
    assert head_response.headers["content-type"].startswith("application/json")
    assert head_response.text == ""


def test_existing_endpoints_retain_authentication_and_responses(
    client: TestClient,
) -> None:
    """Existing API routes keep their normal handlers, auth, and method errors."""
    health_response = client.get(
        "/api/health",
        headers={"Accept": "text/html"},
    )
    assert health_response.status_code == 200
    assert health_response.headers["content-type"].startswith("application/json")
    assert health_response.json()["status"] == "ok"

    auth_response = client.get(
        "/api/auth/me",
        headers={"Accept": "text/html"},
    )
    assert auth_response.status_code == 200
    assert auth_response.json() == {
        "authenticated": False,
    }

    unprotected_post = client.post("/api/health", headers={"Accept": "text/html"})
    assert unprotected_post.status_code == 403

    client.cookies.set(CSRF_COOKIE, "csrf-test-token")
    method_response = client.post(
        "/api/health",
        headers={"Accept": "text/html", CSRF_HEADER: "csrf-test-token"},
    )
    assert method_response.status_code == 405
    assert method_response.headers["content-type"].startswith("application/json")

    unknown_api_response = client.post(
        "/api/unknown-endpoint",
        headers={"Accept": "text/html", CSRF_HEADER: "csrf-test-token"},
    )
    assert unknown_api_response.status_code == 404
    assert unknown_api_response.headers["content-type"].startswith("application/json")
    assert unknown_api_response.json() == {"detail": "Not Found"}


def test_existing_assets_retain_contents_and_content_types(
    client: TestClient,
) -> None:
    """Built frontend assets are served with correct MIME types and body contents."""
    js_response = client.get("/assets/bundle.js")
    assert js_response.status_code == 200
    assert "javascript" in js_response.headers["content-type"]
    assert js_response.text == "console.log('overture-app');"

    css_response = client.get("/assets/styles.css")
    assert css_response.status_code == 200
    assert "text/css" in css_response.headers["content-type"]
    assert css_response.text == "body { margin: 0; }"

    favicon_response = client.get("/favicon.ico")
    assert favicon_response.status_code == 200


def test_missing_assets_and_non_html_deep_links_return_404(
    client: TestClient,
) -> None:
    """Ordinary asset requests and non-HTML deep link requests return 404."""
    missing_asset = client.get("/assets/nonexistent.js")
    assert missing_asset.status_code == 404

    missing_image = client.get("/assets/missing.png", headers={"Accept": "image/*"})
    assert missing_image.status_code == 404

    json_deep_link = client.get(
        "/movies/42-the-matrix",
        headers={"Accept": "application/json"},
    )
    assert json_deep_link.status_code == 404

    json_art_deep_link = client.get(
        "/movies/42-the-matrix/art/poster",
        headers={"Accept": "application/json"},
    )
    assert json_art_deep_link.status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_non_navigation_methods_cannot_receive_shell(
    client: TestClient, method: str
) -> None:
    """Mutating HTTP methods to frontend routes are rejected."""
    request_fn = getattr(client, method)
    response_no_csrf = request_fn(
        "/movies/42-the-matrix",
        headers={"Accept": "text/html"},
    )
    assert response_no_csrf.status_code == 403

    client.cookies.set(CSRF_COOKIE, "csrf-test-token")
    response_with_csrf = request_fn(
        "/movies/42-the-matrix",
        headers={"Accept": "text/html", CSRF_HEADER: "csrf-test-token"},
    )
    assert response_with_csrf.status_code in {404, 405}
    assert response_with_csrf.status_code != 200


def test_missing_frontend_directory_returns_404(
    tmp_path: Path,
    app_config: Settings,
    database: Database,
) -> None:
    """When frontend build directory is missing, routes return 404."""
    nonexistent_dir = tmp_path / "does_not_exist"
    runtime = build_runtime(
        app_settings=app_config,
        database=database,
        config_dir=tmp_path / "app_config",
    )
    app = create_app(runtime, frontend_dir=nonexistent_dir)
    test_client = TestClient(app)
    try:
        api_res = test_client.get("/api/health")
        assert api_res.status_code == 200

        frontend_res = test_client.get("/movies", headers={"Accept": "text/html"})
        assert frontend_res.status_code == 404
    finally:
        test_client.close()
