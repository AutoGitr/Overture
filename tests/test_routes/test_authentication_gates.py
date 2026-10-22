"""Route-level auth and CSRF gates across routers."""

lazy from fastapi.testclient import TestClient


def test_authenticated_get_routes_reject_missing_session(client: TestClient) -> None:
    for path in (
        "/api/docs",
        "/api/openapi.json",
        "/api/settings",
        "/api/sync/status",
        "/api/library/libraries",
        "/api/media-server/libraries",
        "/api/public-dataset/status",
        "/api/backups",
        "/api/collections",
        "/api/stats",
    ):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == "Not authenticated"


def test_mutating_routes_reject_missing_csrf_before_route_logic(
    client: TestClient,
) -> None:
    for method, path, body in (
        ("post", "/api/sync/run", {}),
        ("post", "/api/sync/stop", {}),
        ("post", "/api/backups", {}),
        ("put", "/api/public-dataset/enabled", {"enabled": True}),
        ("put", "/api/themes/1", {"youtube_id": "dQw4w9WgXcQ"}),
        ("post", "/api/bulk/assets", {}),
        ("post", "/api/asset-manager/scan", {}),
        ("post", "/api/server-audit/scan", {}),
        ("delete", "/api/job-snapshots/sync?finished_at=finish", {}),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 403, path
        assert response.json() == {"detail": "Invalid CSRF token"}
