"""Password hashing policy, credential-bound sessions and bounded hashing work."""

lazy import asyncio
lazy import threading

lazy import pytest
lazy from argon2 import PasswordHasher, Type
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.passwords import hash_password, validate_hash, verify_password
lazy from overture.schemas.auth import LoginRequest
lazy from overture.services.auth import AuthService


async def test_reset_invalidates_previous_sessions(
    app_config: Settings, database: Database
) -> None:
    original = AuthService(app_config, database)
    issued = await original.new_session()
    assert (
        await AuthService(app_config, database).token_expiry(issued.token) is not None
    )
    changed = app_config.model_copy(
        update={
            "APP_PASSWORD_HASH": SecretStr(hash_password("a different long password"))
        }
    )
    restarted = AuthService(changed, database)
    assert await restarted.token_expiry(issued.token) is None
    new_session = await restarted.new_session()
    assert await restarted.token_expiry(new_session.token) is not None


async def test_hash_work_is_limited_across_client_addresses(
    app_config: Settings, database: Database
) -> None:
    release = threading.Event()
    entered = threading.Event()
    guard = threading.Lock()
    active = 0
    peak = 0

    def verify(_: bytes, __: bytes) -> bool:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
        try:
            assert release.wait(timeout=5)
            return False
        finally:
            with guard:
                active -= 1

    auth = AuthService(app_config, database, password_verifier=verify)
    tasks = [
        asyncio.create_task(
            auth.login(
                LoginRequest(password=SecretStr("a long test password")),
                socket_ip=f"192.0.2.{index}",
                x_forwarded_for="",
            )
        )
        for index in range(8)
    ]
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert active == 2
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert peak == 2
    assert all(isinstance(result, Exception) for result in results)


@pytest.mark.parametrize(
    "password",
    [
        "x",
        " ",
        "short",
        "a long simple password",
        "  long password with spaces  ",
        "\u00e9" * 50,
        "\u00e9" * 512,
        "x" * 1024,
    ],
)
def test_password_round_trip_preserves_input(password: str) -> None:
    encoded = hash_password(password)
    assert validate_hash(encoded) == encoded
    assert verify_password(password.encode(), encoded.encode())
    assert not verify_password(b"wrong", encoded.encode())


@pytest.mark.parametrize("password", ["", "x" * 1025, "\u00e9" * 513])
def test_creation_limits(password: str) -> None:
    with pytest.raises(ValueError, match=r"empty|UTF-8 bytes"):
        hash_password(password)


@pytest.mark.parametrize(
    "encoded",
    [
        "$2b$12$" + "a" * 53,
        "not-a-hash",
        "$argon2id$v=19$m=999999,t=2,p=1$aaaa$bbbb",
        "$argon2i$v=19$m=19456,t=2,p=1$c2FsdHNhbHQ$ZGlnZXN0",
    ],
)
def test_rejects_unsupported_hashes(encoded: str) -> None:
    with pytest.raises(ValueError, match="overture password hash"):
        validate_hash(encoded)


def test_accepts_standard_external_argon2id_hash() -> None:
    owasp_hash = PasswordHasher(
        memory_cost=64 * 1024, time_cost=3, parallelism=4, type=Type.ID
    ).hash("external-password")
    assert validate_hash(owasp_hash) == owasp_hash
    assert verify_password(b"external-password", owasp_hash.encode())
