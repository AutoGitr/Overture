"""Authentication behavior with injected configuration, clocks, and verifiers."""

lazy import logging
lazy from datetime import timedelta
lazy from ipaddress import ip_network

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.models.auth_session import AuthSession
lazy from overture.db.session import Database
lazy from overture.schemas.auth import LoginRequest
lazy from overture.services.auth import AuthService
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now


async def test_sessions_survive_service_restart_and_revoke(
    app_config: Settings, database: Database
) -> None:
    first = AuthService(app_config, database)
    second = AuthService(app_config, database)
    token = (await first.new_session()).token
    assert await first.token_expiry(token) is not None
    assert await second.token_expiry(token) is not None
    assert await first.token_expiry("not-a-token") is None
    await second.revoke(token)
    assert await first.token_expiry(token) is None


async def test_session_storage_hashes_cookie_and_enforces_expiry(
    auth_service: AuthService, database: Database
) -> None:
    issued = await auth_service.new_session()
    digest = auth_service.token_hash(issued.token)
    async with database.write_session() as session:
        assert await session.get(AuthSession, issued.token) is None
        stored = await session.get(AuthSession, digest)
        assert stored is not None
        assert stored.id_token is None
        stored.expires_at = utc_now() - timedelta(seconds=1)
        session.add(stored)
    assert await auth_service.token_expiry(issued.token) is None
    await auth_service.new_session()
    async with database.read_session() as session:
        assert await session.get(AuthSession, digest) is None


@pytest.mark.parametrize(
    ("proxies", "forwarded", "expected"),
    [
        ((), "198.51.100.20", "10.0.0.10"),
        (
            ("10.0.0.0/8", "203.0.113.5/32"),
            "198.51.100.20, 203.0.113.5",
            "198.51.100.20",
        ),
        (("10.0.0.0/8",), "198.51.100.20, bad-ip", "10.0.0.10"),
    ],
)
async def test_client_ip_respects_only_trusted_proxies(
    app_config: Settings,
    database: Database,
    proxies: tuple[str, ...],
    forwarded: str,
    expected: str,
) -> None:
    config = app_config.model_copy(
        update={"TRUSTED_PROXY_CIDRS": tuple(map(ip_network, proxies))}
    )
    service = AuthService(config, database, password_verifier=_never_verify)
    body = LoginRequest.model_validate({"password": "wrong"})
    for _ in range(5):
        with pytest.raises(PublicServiceError, match="Invalid credentials"):
            await service.login(body, socket_ip="10.0.0.10", x_forwarded_for=forwarded)
    with pytest.raises(PublicServiceError) as error:
        await service.login(body, socket_ip=expected, x_forwarded_for="")
    assert error.value.status_code == 429


def _never_verify(_password: bytes, _hash: bytes) -> bool:
    return False


async def test_rate_limit_expires_and_is_isolated_between_instances(
    app_config: Settings,
    database: Database,
) -> None:
    now = 1000.0
    first = AuthService(
        app_config, database, clock=lambda: now, password_verifier=_never_verify
    )
    second = AuthService(
        app_config, database, clock=lambda: now, password_verifier=_never_verify
    )
    body = LoginRequest.model_validate({"password": "wrong"})

    async def attempt(service: AuthService, status: int) -> None:
        with pytest.raises(PublicServiceError) as error:
            await service.login(body, socket_ip="203.0.113.1", x_forwarded_for="")
        assert error.value.status_code == status

    for _ in range(5):
        await attempt(first, 401)
    await attempt(first, 429)
    await attempt(second, 401)
    now += 61
    await attempt(first, 401)


async def test_failed_and_refused_sign_ins_are_warnings_naming_the_client(
    app_config: Settings,
    database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = AuthService(app_config, database, password_verifier=_never_verify)
    body = LoginRequest.model_validate({"password": "hunter2-attempt"})
    caplog.set_level(logging.WARNING, logger="overture.services.auth")

    for _ in range(6):
        with pytest.raises(PublicServiceError):
            await service.login(body, socket_ip="203.0.113.7", x_forwarded_for="")

    messages = [(record.levelno, record.getMessage()) for record in caplog.records]
    assert messages == [
        *[(logging.WARNING, "Sign-in from 203.0.113.7 failed: wrong password")] * 5,
        (logging.WARNING, "Sign-in from 203.0.113.7 refused: too many attempts"),
    ]


async def test_rate_limit_keeps_a_bounded_number_of_clients(
    app_config: Settings,
    database: Database,
) -> None:
    service = AuthService(
        app_config, database, clock=lambda: 1000, password_verifier=_never_verify
    )
    body = LoginRequest.model_validate({"password": "wrong"})
    for _ in range(5):
        with pytest.raises(PublicServiceError):
            await service.login(body, socket_ip="198.51.0.0", x_forwarded_for="")
    for index in range(1, 1050):
        with pytest.raises(PublicServiceError):
            await service.login(
                LoginRequest.model_validate({"password": "wrong"}),
                socket_ip=f"198.51.{index // 256}.{index % 256}",
                x_forwarded_for="",
            )
    # The oldest exhausted client is evicted when the registry reaches capacity.
    with pytest.raises(PublicServiceError) as error:
        await service.login(body, socket_ip="198.51.0.0", x_forwarded_for="")
    assert error.value.status_code == 401


async def test_revoke_unrecognised_token_returns_none(
    auth_service: AuthService,
) -> None:
    assert await auth_service.revoke(None) is None
    assert await auth_service.revoke("") is None
    assert await auth_service.revoke("short") is None
    assert await auth_service.revoke("x" * 43) is None


async def test_require_token_validates_presence_and_expiration(
    auth_service: AuthService,
) -> None:
    with pytest.raises(PublicServiceError, match="Not authenticated") as missing:
        await auth_service.require_token(None)
    assert missing.value.status_code == 401

    with pytest.raises(PublicServiceError, match="Not authenticated") as empty:
        await auth_service.require_token("")
    assert empty.value.status_code == 401

    with pytest.raises(
        PublicServiceError, match="Invalid or expired session"
    ) as expired:
        await auth_service.require_token("invalid-session-token-43-characters-long!!")
    assert expired.value.status_code == 401

    valid_session = await auth_service.new_session()
    await auth_service.require_token(valid_session.token)
