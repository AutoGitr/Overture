"""Runtime-owned authentication, token issuance, and login rate limits."""

lazy import asyncio
lazy import hashlib
lazy import ipaddress
lazy import logging
lazy import secrets
lazy import time
lazy from collections.abc import Callable
lazy from dataclasses import dataclass, field
lazy from datetime import datetime, timedelta

lazy from sqlmodel import col, delete

lazy from ..config import Settings
lazy from ..db.models.auth_session import AuthSession
lazy from ..db.session import Database
lazy from ..passwords import MAX_PASSWORD_BYTES, verify_password
lazy from ..schemas.auth import AuthConfig, LoginRequest, LoginResponse, MeResponse
lazy from ..utils.cache import TimedRegistry
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.http_security import new_csrf_token
lazy from ..utils.locks import KeyedLock
lazy from ..utils.threads import owned_thread
lazy from ..utils.time import utc_now
lazy from .oidc import OIDCService

logger = logging.getLogger(__name__)

_RATE_LIMIT = 5
_RATE_WINDOW = 60
_MAX_TRACKED_IPS = 1000


@dataclass(slots=True, frozen=True)
class LoginSession:
    """Authenticated session material for cookie issuance."""

    response: LoginResponse
    token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    max_age: int
    secure: bool


class AuthService:
    """Keep credentials and failed-login state local to one application."""

    def __init__(
        self,
        app_config: Settings,
        database: Database,
        *,
        clock: Callable[[], float] = time.monotonic,
        password_verifier: Callable[[bytes, bytes], bool] = verify_password,
    ) -> None:
        self._config = app_config
        self._database = database
        self._clock = clock
        self._password_verifier = password_verifier
        self._password_slots = asyncio.Semaphore(2)
        self._credential_fingerprint = (
            self.token_hash(app_config.APP_PASSWORD_HASH.get_secret_value())
            if app_config.password_enabled
            else None
        )
        # Password and OIDC entry points share the per-client attempt budget.
        self._login_attempts: TimedRegistry[str, list[float]] = TimedRegistry(
            maxsize=_MAX_TRACKED_IPS,
            ttl_seconds=_RATE_WINDOW,
        )
        self._login_locks = KeyedLock[str]()
        self.oidc = OIDCService(app_config) if app_config.oidc_enabled else None
        # OIDC sessions are bound to this issuer; None identifies password sessions.
        self._issuer = (
            str(app_config.OIDC_ISSUER_URL) if app_config.oidc_enabled else None
        )

    def _recent_attempts(self, ip: str, now: float) -> list[float]:
        attempts = self._login_attempts.get(ip, now) or []
        return [stamp for stamp in attempts if now - stamp < _RATE_WINDOW]

    async def token_expiry(self, token: str) -> datetime | None:
        """Look up a live session; never cache authorization across requests."""
        if len(token) != 43:
            return None
        async with self._database.read_session() as session:
            stored = await session.get(AuthSession, self.token_hash(token))
        if stored is None or stored.expires_at <= utc_now():
            return None
        if stored.oidc_issuer is not None:
            if not self._config.oidc_enabled or stored.oidc_issuer != self._issuer:
                return None
        elif (
            not self._config.password_enabled
            or stored.credential_fingerprint != self._credential_fingerprint
        ):
            return None
        return stored.expires_at

    @staticmethod
    def token_hash(token: str) -> str:
        """Hash a high-entropy credential before persistence."""
        return hashlib.sha256(token.encode()).hexdigest()

    def session_seconds(self) -> int:
        """Use the same absolute lifetime for every authentication method."""
        return self._config.SESSION_EXPIRY_DAYS * 86400

    async def new_session(self, *, id_token: str | None = None) -> LoginSession:
        """Persist a fresh opaque credential; retain only the OIDC logout hint."""
        token = secrets.token_urlsafe(32)
        now = utc_now()
        issuer = self._issuer if id_token is not None else None
        fingerprint = None if id_token is not None else self._credential_fingerprint
        async with self._database.write_session() as session:
            await session.exec(
                delete(AuthSession).where(col(AuthSession.expires_at) <= now)
            )
            session.add(
                AuthSession(
                    token_hash=self.token_hash(token),
                    expires_at=now + timedelta(seconds=self.session_seconds()),
                    oidc_issuer=issuer,
                    credential_fingerprint=fingerprint,
                    id_token=id_token,
                )
            )
        return LoginSession(
            response=LoginResponse(status="ok"),
            token=token,
            csrf_token=new_csrf_token(),
            max_age=self.session_seconds(),
            secure=self._config.secure_cookies,
        )

    async def revoke(self, token: str | None) -> str | None:
        """Revoke atomically before provider I/O and return a valid logout hint."""
        if not token or len(token) != 43:
            return None
        async with self._database.write_session() as session:
            stored = await session.get(AuthSession, self.token_hash(token))
            if stored is None:
                return None
            await session.delete(stored)
        return stored.id_token if stored.oidc_issuer == self._issuer else None

    def check_oidc_rate(self, socket_ip: str, x_forwarded_for: str) -> None:
        """Bound login-start traffic before contacting the identity provider."""
        key = self._client_ip(socket_ip, x_forwarded_for)
        now = self._clock()
        attempts = self._recent_attempts(key, now)
        if len(attempts) >= _RATE_LIMIT:
            raise PublicServiceError(429, "Too many login attempts. Try again later.")
        self._login_attempts.set(key, [*attempts, now], now)

    def close(self) -> None:
        """Release transient authentication state owned by the runtime."""
        if self.oidc is not None:
            self.oidc.close()

    def _client_ip(self, socket_ip: str, x_forwarded_for: str) -> str:
        if not self._config.is_trusted_proxy(socket_ip):
            return socket_ip
        forwarded: list[str] = []
        for part in x_forwarded_for.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            try:
                forwarded.append(str(ipaddress.ip_address(candidate)))
            except ValueError:
                return socket_ip
        for candidate in reversed(forwarded):
            if not self._config.is_trusted_proxy(candidate):
                return candidate
        return forwarded[0] if forwarded else socket_ip

    def _password_matches(self, password: str) -> bool:
        try:
            password_bytes = password.encode("utf-8")
        except UnicodeEncodeError:
            return False
        if len(password_bytes) > MAX_PASSWORD_BYTES:
            return False
        return self._password_verifier(
            password_bytes,
            self._config.APP_PASSWORD_HASH.get_secret_value().encode("utf-8"),
        )

    async def login(
        self,
        body: LoginRequest,
        *,
        socket_ip: str,
        x_forwarded_for: str,
    ) -> LoginSession:
        """Authenticate while serializing checks and failures for each client."""
        if not self._config.password_enabled:
            raise PublicServiceError(404, "Password login is disabled")
        client_ip = self._client_ip(socket_ip, x_forwarded_for)
        async with self._login_locks.acquire(client_ip):
            if len(self._recent_attempts(client_ip, self._clock())) >= _RATE_LIMIT:
                logger.warning("Sign-in from %s refused: too many attempts", client_ip)
                raise PublicServiceError(
                    429, "Too many login attempts. Try again later."
                )
            async with self._password_slots:
                password_valid = await owned_thread(
                    self._password_matches, body.password.get_secret_value()
                )
            if not password_valid:
                now = self._clock()
                self._login_attempts.set(
                    client_ip,
                    [*self._recent_attempts(client_ip, now), now],
                    now,
                )
                logger.warning("Sign-in from %s failed: wrong password", client_ip)
                raise PublicServiceError(401, "Invalid credentials")
        return await self.new_session()

    async def require_token(self, token: str | None) -> None:
        """Require a live application session."""
        if self._config.AUTH_MODE == "none":
            return
        if not token:
            raise PublicServiceError(401, "Not authenticated")
        if await self.token_expiry(token) is None:
            raise PublicServiceError(401, "Invalid or expired session")

    async def me_response(self, token: str | None) -> MeResponse:
        """Return session status without exposing session material."""
        if self._config.AUTH_MODE == "none":
            return MeResponse(authenticated=True)
        return MeResponse(authenticated=bool(token and await self.token_expiry(token)))

    def public_config(self) -> AuthConfig:
        """Return only public login presentation settings."""
        return AuthConfig(
            auth_mode=self._config.AUTH_MODE,
            oidc_enabled=self._config.oidc_enabled,
            display_name=self._config.OIDC_DISPLAY_NAME,
            auto_login=(
                self._config.OIDC_AUTO_LOGIN if self._config.oidc_enabled else False
            ),
        )

    def cookie_security(self) -> tuple[bool, int]:
        """Return shared cookie security and lifetime."""
        return self._config.secure_cookies, self.session_seconds()
