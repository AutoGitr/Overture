"""Exercise the real OIDC protocol, signature verification, and admission policy."""

lazy import asyncio
lazy import time
lazy from typing import Any
lazy from urllib.parse import parse_qs, urlsplit

lazy import httpx2
lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient
lazy from joserfc.jwk import ECKey, RSAKey
lazy from pydantic import ValidationError

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.dependencies import get_auth
lazy from overture.services.auth import AuthService
lazy from overture.services.oidc import (
    TRANSACTION_COOKIE,
    OIDCError,
    OIDCService,
    validate_return_to,
)
lazy from overture.utils.security import sanitise_error, sanitise_for_output
lazy from tests.oidc_provider import TestOIDCProvider


@pytest.fixture
def oidc_config(app_config: Settings) -> Settings:
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
    return Settings(**values)


@pytest.fixture
def provider() -> TestOIDCProvider:
    return TestOIDCProvider()


@pytest.fixture
def oidc(oidc_config: Settings, provider: TestOIDCProvider) -> OIDCService:
    return OIDCService(oidc_config, transport=httpx2.MockTransport(provider.handle))


async def begin(
    oidc: OIDCService, provider: TestOIDCProvider
) -> tuple[dict[str, str], str]:
    url, binding = await oidc.start("/shows/42-example/art", None)
    code, state = provider.authorize(url)
    return {"code": code, "state": state}, binding


async def test_full_flow_uses_pkce_nonce_and_stable_subject(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    identity = await oidc.complete(params, binding)
    assert identity.subject == "admin-123"
    assert identity.return_to == "/shows/42-example/art"
    assert identity.issuer == provider.issuer
    token_request = next(
        request for request in provider.requests if request.url.path == "/token"
    )
    assert token_request.headers["authorization"].startswith("Basic ")
    assert "code_verifier=" in token_request.content.decode()
    with pytest.raises(OIDCError, match="expired"):
        await oidc.complete(params, binding)


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.test"},
        {"aud": "another-client"},
        {"azp": "another-client"},
        {"aud": ["overture", "another-client"]},
        {"exp": 1},
        {"iat": time.time() + 3600},
        {"nbf": time.time() + 3600},
        {"nonce": "wrong"},
        {"nonce": None},
        {"nonce": "wrong", "nonce_supported": False},
        {"exp": None},
        {"at_hash": "wrong"},
        {"sub": ""},
        {"sub": 42},
    ],
)
async def test_rejects_invalid_signed_claims(
    oidc: OIDCService, provider: TestOIDCProvider, overrides: dict[str, Any]
) -> None:
    provider.claim_overrides = overrides
    params, binding = await begin(oidc, provider)
    with pytest.raises(OIDCError, match="invalid"):
        await oidc.complete(params, binding)


@pytest.mark.parametrize(
    "groups", [None, "overture-admins", [], ["OVERTURE-ADMINS"], [42], ["users"]]
)
async def test_leaves_group_authorization_to_provider(
    oidc: OIDCService, provider: TestOIDCProvider, groups: object
) -> None:
    provider.claim_overrides = {"groups": groups}
    params, binding = await begin(oidc, provider)
    assert (await oidc.complete(params, binding)).subject == "admin-123"


async def test_cross_browser_state_and_concurrent_replay(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    with pytest.raises(OIDCError, match="expired"):
        await oidc.complete(params, "another-browser")
    results = await asyncio.gather(
        oidc.complete(params, binding),
        oidc.complete(params, binding),
        return_exceptions=True,
    )
    assert sum(isinstance(result, OIDCError) for result in results) == 1
    assert sum(request.url.path == "/token" for request in provider.requests) == 1


async def test_state_mismatch_consumes_attempt(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    with pytest.raises(OIDCError, match="invalid"):
        await oidc.complete(params | {"state": "\u00e9"}, binding)
    with pytest.raises(OIDCError, match="expired"):
        await oidc.complete(params, binding)


async def test_expiry_and_new_attempt_supersede_old(
    oidc_config: Settings, provider: TestOIDCProvider
) -> None:
    now = 1000.0
    service = OIDCService(
        oidc_config, clock=lambda: now, transport=httpx2.MockTransport(provider.handle)
    )
    params, binding = await begin(service, provider)
    await service.start("/", binding)
    with pytest.raises(OIDCError, match="expired"):
        await service.complete(params, binding)
    params, binding = await begin(service, provider)
    now += 601
    with pytest.raises(OIDCError, match="expired"):
        await service.complete(params, binding)


async def test_key_rotation_refreshes_once(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    await oidc.complete(params, binding)
    provider.key = RSAKey.generate_key(2048, parameters={"kid": "rotated"})
    params, binding = await begin(oidc, provider)
    await oidc.complete(params, binding)
    assert sum(request.url.path == "/jwks" for request in provider.requests) == 2
    provider.key = RSAKey.generate_key(2048, parameters={"kid": "rotated-again"})
    params, binding = await begin(oidc, provider)
    await oidc.complete(params, binding)
    assert sum(request.url.path == "/jwks" for request in provider.requests) == 3


async def test_rejects_invalid_signature_with_known_key_id(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    await oidc.complete(params, binding)
    provider.key = RSAKey.generate_key(2048, parameters={"kid": "first"})
    params, binding = await begin(oidc, provider)
    with pytest.raises(OIDCError, match="invalid"):
        await oidc.complete(params, binding)
    assert sum(request.url.path == "/jwks" for request in provider.requests) == 1


async def test_es256_and_client_secret_basic(
    oidc_config: Settings, provider: TestOIDCProvider
) -> None:
    provider.key = ECKey.generate_key("P-256", parameters={"kid": "ec-key"})
    service = OIDCService(oidc_config, transport=httpx2.MockTransport(provider.handle))
    params, binding = await begin(service, provider)
    identity = await service.complete(params, binding)
    assert identity.subject == "admin-123"
    token_request = next(
        request for request in provider.requests if request.url.path == "/token"
    )
    assert token_request.headers["authorization"].startswith("Basic ")
    assert "client_secret" not in token_request.content.decode()


async def test_bounded_registry_and_shutdown_discard_pending_logins(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    for _ in range(1000):
        await oidc.start("/", None)
    with pytest.raises(OIDCError, match="expired"):
        await oidc.complete(params, binding)
    params, binding = await begin(oidc, provider)
    oidc.close()
    with pytest.raises(OIDCError, match="expired"):
        await oidc.complete(params, binding)


@pytest.mark.parametrize(
    "overrides",
    [
        {"issuer": "https://attacker.test"},
        {"token_endpoint": "http://insecure.test/token"},
        {"code_challenge_methods_supported": ["plain"]},
        {"id_token_signing_alg_values_supported": ["HS256"]},
    ],
)
async def test_discovery_fails_closed(
    oidc: OIDCService, provider: TestOIDCProvider, overrides: dict[str, Any]
) -> None:
    provider.metadata_overrides = overrides
    with pytest.raises(OIDCError, match="unavailable"):
        await oidc.start("/", None)


async def test_provider_failure_does_not_retry_code_exchange(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    provider.fail_path = "/token"
    with pytest.raises(OIDCError):
        await oidc.complete(params, binding)
    assert sum(request.url.path == "/token" for request in provider.requests) == 1


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.test",
        "//evil.test",
        "/\\evil.test",
        "/api/auth/oidc/login",
        "/movies/../../evil",
        "/%2Fevil.test",
        "/movies/%0aevil",
        "http://[::1:80",
    ],
)
def test_rejects_unsafe_navigation(target: str) -> None:
    with pytest.raises(OIDCError):
        validate_return_to(target)


async def test_callback_with_provider_error(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    with pytest.raises(OIDCError, match="denied"):
        await oidc.complete(params | {"error": "access_denied"}, binding)


async def test_callback_with_mismatched_iss_or_missing_code(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    params, binding = await begin(oidc, provider)
    with pytest.raises(OIDCError, match="invalid"):
        await oidc.complete(params | {"iss": "https://wrong.test"}, binding)

    params2, binding2 = await begin(oidc, provider)
    params_no_code = {k: v for k, v in params2.items() if k != "code"}
    with pytest.raises(OIDCError, match="invalid"):
        await oidc.complete(params_no_code, binding2)


@pytest.mark.parametrize(
    "change",
    [
        {"OIDC_CLIENT_ID": ""},
        {"OIDC_CLIENT_SECRET": ""},
        {"APP_URL": ""},
        {"APP_URL": "http://example.test"},
        {"OIDC_ISSUER_URL": "http://localhost:80@evil.test"},
        {"OIDC_ISSUER_URL": "https://idp.example.test/?tenant=one"},
        {"OIDC_ISSUER_URL": "https://idp.example.test/#fragment"},
    ],
)
def test_configuration_requires_safe_complete_settings(
    oidc_config: Settings, change: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        Settings(**(oidc_config.model_dump() | change))


def test_oidc_mode_does_not_require_password(oidc_config: Settings) -> None:
    values = oidc_config.model_dump(exclude={"APP_PASSWORD_HASH"})
    configured = Settings(**values)
    assert configured.oidc_enabled
    assert not configured.password_enabled


def test_both_mode_requires_password_and_oidc(oidc_config: Settings) -> None:
    values = oidc_config.model_dump()
    values["AUTH_MODE"] = "both"
    configured = Settings(**values)
    assert configured.oidc_enabled
    assert configured.password_enabled

    with pytest.raises(ValidationError):
        Settings.model_validate(values | {"APP_PASSWORD_HASH": ""})

    with pytest.raises(ValidationError):
        Settings.model_validate(values | {"OIDC_CLIENT_ID": ""})


def test_routes_issue_oidc_cookies_and_disable_password_login(
    client: TestClient,
    test_app: FastAPI,
    database: Database,
    oidc_config: Settings,
    oidc: OIDCService,
    provider: TestOIDCProvider,
) -> None:
    def unexpected_password_verification(_password: bytes, _hash: bytes) -> bool:
        pytest.fail("Password verification must not run in OIDC mode")

    auth = AuthService(
        oidc_config, database, password_verifier=unexpected_password_verification
    )
    auth.oidc = oidc
    test_app.dependency_overrides[get_auth] = lambda: auth
    client.base_url = httpx2.URL(oidc_config.APP_URL)
    password_login = client.post("/api/auth/login", json={"password": "password"})
    assert password_login.status_code == 404
    assert password_login.json() == {"detail": "Password login is disabled"}
    assert "overture_token" not in client.cookies
    response = client.get(
        "/api/auth/oidc/login?return_to=/shows", follow_redirects=False
    )
    assert response.status_code == 302
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    code, state = provider.authorize(response.headers["location"])
    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )
    assert callback.headers["location"] == "/shows"
    assert "SameSite=strict" in "\n".join(callback.headers.get_list("set-cookie"))
    assert TRANSACTION_COOKIE not in client.cookies
    assert client.get("/api/auth/me").json() == {
        "authenticated": True,
    }
    assert (
        client.post("/api/auth/login", json={"password": "password"}).status_code == 404
    )
    assert client.post("/api/auth/logout").status_code == 403
    logout = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": client.cookies["overture_csrf"]}
    )
    assert logout.status_code == 200
    assert client.get("/api/auth/me").json()["authenticated"] is False


def test_oidc_disabled_and_rate_limit(
    client: TestClient,
    test_app: FastAPI,
    database: Database,
    oidc_config: Settings,
    oidc: OIDCService,
) -> None:
    assert client.get("/api/auth/oidc/login").status_code == 404
    auth = AuthService(oidc_config, database)
    auth.oidc = oidc
    test_app.dependency_overrides[get_auth] = lambda: auth
    for _ in range(5):
        assert (
            client.get("/api/auth/oidc/login", follow_redirects=False).status_code
            == 302
        )
    assert client.get("/api/auth/oidc/login", follow_redirects=False).status_code == 429


async def test_sessions_are_bound_to_the_active_auth_method_and_issuer(
    app_config: Settings, oidc_config: Settings, database: Database
) -> None:
    auth = AuthService(oidc_config, database)
    password_auth = AuthService(app_config, database)
    oidc_session = await auth.new_session(id_token="test-id-token")
    password_session = await password_auth.new_session()
    assert await auth.token_expiry(oidc_session.token) is not None
    assert await auth.token_expiry(password_session.token) is None
    assert await password_auth.token_expiry(password_session.token) is not None
    assert await password_auth.token_expiry(oidc_session.token) is None
    assert oidc_session.max_age == password_session.max_age == 7 * 86400
    other_config = Settings.model_validate(
        oidc_config.model_dump() | {"OIDC_ISSUER_URL": "https://other.test"}
    )
    other = AuthService(other_config, database)
    assert await other.token_expiry(oidc_session.token) is None
    assert await other.token_expiry(password_session.token) is None

    both_config = Settings.model_validate(
        oidc_config.model_dump() | {"AUTH_MODE": "both"}
    )
    both_auth = AuthService(both_config, database)
    assert await both_auth.token_expiry(oidc_session.token) is not None
    assert await both_auth.token_expiry(password_session.token) is not None


def test_public_config_contains_only_presentation(client: TestClient) -> None:
    response = client.get("/api/auth/config")
    assert response.json() == {
        "auth_mode": "password",
        "oidc_enabled": False,
        "display_name": "Sign in with SSO",
        "auto_login": False,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", ["", "?tenant=one"])
async def test_rp_logout_uses_discovered_endpoint(
    oidc: OIDCService, provider: TestOIDCProvider, query: str
) -> None:
    provider.metadata_overrides = {
        "end_session_endpoint": provider.issuer + "/logout" + query
    }
    url = urlsplit(await oidc.logout_url("signed-id-token"))
    assert url.path == "/logout"
    assert parse_qs(url.query) == {
        "id_token_hint": ["signed-id-token"],
        "client_id": ["overture"],
        "post_logout_redirect_uri": ["https://overture.example.test/?autologin=0"],
        **({"tenant": ["one"]} if query else {}),
    }


async def test_logout_without_provider_support_or_connectivity_is_local(
    oidc: OIDCService, provider: TestOIDCProvider
) -> None:
    provider.metadata_overrides = {"end_session_endpoint": None}
    assert await oidc.logout_url("id-token") == "/?autologin=0"
    oidc.close()
    provider.fail_path = "/.well-known/openid-configuration"
    assert await oidc.logout_url("id-token") == "/?autologin=0"


def test_logout_invalidates_pending_attempt(
    client: TestClient,
    test_app: FastAPI,
    database: Database,
    oidc_config: Settings,
    oidc: OIDCService,
    provider: TestOIDCProvider,
) -> None:
    auth = AuthService(oidc_config, database)
    auth.oidc = oidc
    test_app.dependency_overrides[get_auth] = lambda: auth
    client.base_url = httpx2.URL(oidc_config.APP_URL)
    login = client.get("/api/auth/oidc/login", follow_redirects=False)
    binding = client.cookies[TRANSACTION_COOKIE]
    code, state = provider.authorize(login.headers["location"])
    client.cookies.set("overture_csrf", "logout-csrf")
    client.post("/api/auth/logout", headers={"X-CSRF-Token": "logout-csrf"})
    # Even restoring the cleared browser cookie cannot resurrect the transaction.
    client.cookies.set(TRANSACTION_COOKIE, binding)
    response = client.get(
        "/api/auth/oidc/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/?autologin=0&auth_error=oidc_expired"
    assert "overture_token" not in client.cookies


@pytest.mark.parametrize(
    "params",
    [
        [("state", "one"), ("state", "two"), ("code", "value")],
        [("error", "access_denied"), ("error_description", "unsafe-description")],
    ],
)
def test_callback_errors_clear_cookies_and_expose_only_fixed_codes(
    client: TestClient,
    test_app: FastAPI,
    database: Database,
    oidc_config: Settings,
    oidc: OIDCService,
    params: list[tuple[str, str]],
) -> None:
    auth = AuthService(oidc_config, database)
    auth.oidc = oidc
    test_app.dependency_overrides[get_auth] = lambda: auth
    client.base_url = httpx2.URL(oidc_config.APP_URL)
    client.get("/api/auth/oidc/login", follow_redirects=False)
    response = client.get(
        "/api/auth/oidc/callback", params=tuple(params), follow_redirects=False
    )
    assert response.headers["location"] == "/?autologin=0&auth_error=oidc_invalid"
    assert "unsafe-description" not in response.text
    assert TRANSACTION_COOKIE not in client.cookies


def test_oidc_secrets_are_redacted() -> None:
    assert "sensitive" not in sanitise_error(
        "https://app.test/callback?code=sensitive&state=sensitive&nonce=sensitive&code_verifier=sensitive"
    )
    assert sanitise_for_output({"code": "sensitive", "nonce": "sensitive"}) == {
        "code": "[REDACTED]",
        "nonce": "[REDACTED]",
    }
