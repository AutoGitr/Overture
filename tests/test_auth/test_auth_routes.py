"""Auth route behavior and cookie contracts."""

lazy import asyncio
lazy import json

lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.dependencies import get_auth
lazy from overture.schemas.auth import LoginRequest
lazy from overture.services.auth import AuthService
lazy from overture.services.oidc import OIDCError
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.http_security import CSRF_COOKIE


def test_login_success_sets_session_and_csrf_cookies(
    client: TestClient,
    test_app: FastAPI,
    app_config: Settings,
    database: Database,
) -> None:
    app_config.APP_URL = "https://overture.example.test"

    def accept_password(_password: bytes, _hash: bytes) -> bool:
        return True

    service = AuthService(app_config, database, password_verifier=accept_password)
    test_app.dependency_overrides[get_auth] = lambda: service

    response = client.post(
        "/api/auth/login",
        json={"password": "correct"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    set_cookie = "\n".join(response.headers.get_list("set-cookie"))
    assert "overture_token=" in set_cookie
    assert f"{CSRF_COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" in set_cookie
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"


@pytest.mark.parametrize("password", ["x" * 1025, "\u00e9" * 513, "\ud800"])
def test_login_rejects_passwords_beyond_byte_limit(
    client: TestClient, password: str
) -> None:
    response = client.post(
        "/api/auth/login",
        content=json.dumps({"password": password}),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


async def test_concurrent_failed_logins_share_one_rate_limit(
    app_config: Settings, database: Database
) -> None:
    password_checks: list[bytes] = []

    def reject_password(password: bytes, _hash: bytes) -> bool:
        password_checks.append(password)
        return False

    service = AuthService(app_config, database, password_verifier=reject_password)
    results = await asyncio.gather(
        *(
            service.login(
                LoginRequest.model_validate({"password": "wrong"}),
                socket_ip="198.51.100.40",
                x_forwarded_for="",
            )
            for _ in range(12)
        ),
        return_exceptions=True,
    )

    assert len(password_checks) == 5
    assert (
        sorted(
            result.status_code
            for result in results
            if isinstance(result, PublicServiceError)
        )
        == [401] * 5 + [429] * 7
    )


def test_logout_clears_auth_and_csrf_cookies(client: TestClient) -> None:
    client.cookies.set(CSRF_COOKIE, "logout-token")
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": "logout-token"})

    assert response.status_code == 200
    set_cookie = "\n".join(response.headers.get_list("set-cookie"))
    assert "overture_token=" in set_cookie
    assert f"{CSRF_COOKIE}=" in set_cookie
    assert "Max-Age=0" in set_cookie


def test_logout_requires_csrf(client: TestClient) -> None:
    response = client.post("/api/auth/logout")

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid CSRF token"}


def test_logout_revokes_copied_cookie(
    authenticated_client: TestClient, session_token: str, auth_headers: dict[str, str]
) -> None:
    response = authenticated_client.post("/api/auth/logout", headers=auth_headers)
    assert response.json() == {"status": "ok", "redirect_url": "/?autologin=0"}
    authenticated_client.cookies.set("overture_token", session_token)
    assert authenticated_client.get("/api/auth/me").json() == {"authenticated": False}
    assert authenticated_client.get("/api/settings").status_code == 401


def test_me_returns_false_for_expired_or_invalid_cookie(client: TestClient) -> None:
    client.cookies.set("overture_token", "not-a-jwt")

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False,
    }


def test_oidc_callback_when_disabled_returns_404(client: TestClient) -> None:
    response = client.get("/api/auth/oidc/callback")
    assert response.status_code == 404
    assert response.json() == {"detail": "OIDC login is disabled"}


def test_oidc_login_start_failure_redirects(
    client: TestClient,
    test_app: FastAPI,
    app_config: Settings,
    database: Database,
) -> None:
    service = AuthService(app_config, database)

    class FailingOIDC:
        async def start(self, _return_to: str, _binding: str | None) -> tuple[str, str]:
            raise OIDCError("unavailable")

    service.oidc = FailingOIDC()  # type: ignore[assignment]
    test_app.dependency_overrides[get_auth] = lambda: service
    try:
        response = client.get("/api/auth/oidc/login", follow_redirects=False)
        expected_location = "/?autologin=0&auth_error=oidc_unavailable"
        assert response.headers["location"] == expected_location
    finally:
        test_app.dependency_overrides.pop(get_auth, None)
