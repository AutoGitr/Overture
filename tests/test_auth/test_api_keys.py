"""Named read-only API keys for scripts and dashboards."""

lazy from fastapi.testclient import TestClient

lazy from overture.config import Settings
lazy from overture.utils.http_security import API_KEY_HEADER

PREVIEW = {
    "media_type": "movie",
    "library_id": "1",
    "rule": {
        "criteria": {
            "conditions": [
                {"kind": "field", "field": "year", "operator": "gt", "value": 2000}
            ]
        }
    },
}


def _create(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post("/api/auth/api-keys", json={"name": name}, headers=headers)
    assert response.status_code == 200
    return response.json()["key"]


def test_a_key_is_shown_once_and_listed_by_name_only(
    authenticated_client: TestClient, auth_headers: dict[str, str]
) -> None:
    key = _create(authenticated_client, auth_headers, "  Homepage  ")

    listed = authenticated_client.get("/api/auth/api-keys").json()

    assert [entry["name"] for entry in listed] == ["Homepage"]
    assert key not in str(listed)
    assert set(listed[0]) == {"id", "name", "created_at"}


def test_a_key_reads_without_a_session_but_cannot_change_anything(
    authenticated_client: TestClient, client: TestClient, auth_headers: dict[str, str]
) -> None:
    key = _create(authenticated_client, auth_headers, "Script")
    client.cookies.clear()
    headers = {API_KEY_HEADER: key}

    assert client.get("/api/settings", headers=headers).status_code == 200
    refused = client.put("/api/settings", json={}, headers=headers)
    assert refused.status_code == 403
    assert refused.json() == {"detail": "API keys can only read"}
    assert (
        client.post(
            "/api/auth/api-keys", json={"name": "Escalate"}, headers=headers
        ).status_code
        == 403
    )


def test_a_post_that_only_reads_accepts_a_key(
    authenticated_client: TestClient,
    client: TestClient,
    auth_headers: dict[str, str],
    app_config: Settings,
) -> None:
    key = _create(authenticated_client, auth_headers, "Verifier")
    client.cookies.clear()
    app_config.MEDIA_SERVER = None

    response = client.post(
        "/api/collections/preview", json=PREVIEW, headers={API_KEY_HEADER: key}
    )

    # Past authentication and CSRF, the route itself answers: no media server.
    assert response.status_code == 409


def test_a_wrong_or_revoked_key_is_refused(
    authenticated_client: TestClient, client: TestClient, auth_headers: dict[str, str]
) -> None:
    key = _create(authenticated_client, auth_headers, "Old")
    key_id = authenticated_client.get("/api/auth/api-keys").json()[0]["id"]
    deleted = authenticated_client.delete(
        f"/api/auth/api-keys/{key_id}", headers=auth_headers
    )
    assert deleted.json() == {"status": "deleted"}
    client.cookies.clear()

    for candidate in (key, "not-a-key"):
        response = client.get("/api/settings", headers={API_KEY_HEADER: candidate})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


def test_a_key_beside_a_session_cookie_still_needs_csrf(
    authenticated_client: TestClient, auth_headers: dict[str, str]
) -> None:
    key = _create(authenticated_client, auth_headers, "Mixed")
    # The CSRF check runs before routing, so the route is never reached.

    response = authenticated_client.post(
        "/api/collections/preview", json=PREVIEW, headers={API_KEY_HEADER: key}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid CSRF token"}


def test_key_names_are_unique(
    authenticated_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _create(authenticated_client, auth_headers, "Widget")

    response = authenticated_client.post(
        "/api/auth/api-keys", json={"name": "Widget"}, headers=auth_headers
    )

    assert response.status_code == 409
