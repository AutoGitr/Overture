"""One trusted OIDC provider, with browser-bound single-use login transactions."""

lazy import asyncio
lazy import secrets
lazy import time
lazy from collections.abc import Callable, Mapping
lazy from dataclasses import dataclass, field
lazy from typing import Any, Literal, cast
lazy from urllib.parse import unquote, urlencode, urlsplit

lazy import httpx2
lazy from authlib.integrations.base_client.errors import OAuthError
lazy from authlib.integrations.starlette_client import StarletteOAuth2App
lazy from joserfc.errors import JoseError
lazy from pydantic import BaseModel, ConfigDict, Field

lazy from ..config import API_PREFIX, Settings
lazy from ..utils.cache import TimedRegistry
lazy from ..utils.http_security import SIGNED_OUT_PATH

TRANSACTION_COOKIE = "overture_oidc"
OIDC_PATH = f"{API_PREFIX}/auth/oidc"
# Logout must also receive the binding to invalidate the pending transaction.
TRANSACTION_COOKIE_PATH = f"{API_PREFIX}/auth"
TRANSACTION_SECONDS = 600
_CACHE_SECONDS = 3600

type OIDCErrorCode = Literal["denied", "expired", "unavailable", "invalid"]


class OIDCError(Exception):
    """A fixed public failure code; never a provider-controlled description."""

    def __init__(self, code: OIDCErrorCode) -> None:
        self.code = code
        super().__init__(code)


class ProviderMetadata(BaseModel):
    """Validate the discovery fields used by this integration."""

    model_config = ConfigDict(strict=True)
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    code_challenge_methods_supported: list[str] = Field(default_factory=list)
    id_token_signing_alg_values_supported: list[str]
    end_session_endpoint: str | None = None


@dataclass(slots=True, frozen=True)
class LoginTransaction:
    """Secrets that stay server-side for one login attempt."""

    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    state: str = field(repr=False)
    return_to: str


@dataclass(slots=True, frozen=True)
class OIDCIdentity:
    """Stable identity and safe navigation after successful authorization."""

    issuer: str
    subject: str
    return_to: str
    id_token: str = field(repr=False)


def validate_return_to(value: str) -> str:
    """Accept only application navigation, never an external redirect."""
    decoded = unquote(value)
    try:
        parsed = urlsplit(decoded)
    except ValueError as exc:
        raise OIDCError("invalid") from exc
    if (
        parsed.scheme
        or parsed.netloc
        or not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(char) <= 32 or ord(char) == 127 for char in decoded)
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or not (
            parsed.path in {"/", "/movies", "/shows"}
            or parsed.path.startswith(("/movies/", "/shows/"))
        )
    ):
        raise OIDCError("invalid")
    return value


class OIDCService:
    """Own provider caches and bounded transactions for one application runtime."""

    def __init__(
        self,
        config: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        issuer = str(config.OIDC_ISSUER_URL)
        # Authlib's framework client has an untyped, dynamically composed API.
        self._client: Any = StarletteOAuth2App(
            framework=None,
            name="oidc",
            client_id=config.OIDC_CLIENT_ID,
            client_secret=config.OIDC_CLIENT_SECRET.get_secret_value(),
            server_metadata_url=f"{issuer.rstrip('/')}/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid profile email",
                "token_endpoint_auth_method": "client_secret_basic",
                "code_challenge_method": "S256",
                "timeout": 10,
                "follow_redirects": False,
                "transport": transport,
            },
        )
        self._transactions = TimedRegistry[str, LoginTransaction](
            1000, TRANSACTION_SECONDS
        )
        self._metadata: ProviderMetadata | None = None
        self._metadata_until = 0.0
        self._metadata_lock = asyncio.Lock()

    @property
    def callback_url(self) -> str:
        """Use only the operator's canonical origin for the redirect URI."""
        return f"{self._config.APP_URL}{OIDC_PATH}/callback"

    async def _provider(self) -> ProviderMetadata:
        async with self._metadata_lock:
            if self._metadata is not None and self._clock() < self._metadata_until:
                return self._metadata
            self._client.server_metadata.clear()
            metadata = ProviderMetadata.model_validate(
                await self._client.load_server_metadata()
            )
            if metadata.issuer != str(self._config.OIDC_ISSUER_URL):
                raise ValueError("Unexpected provider issuer")
            for endpoint in (
                metadata.authorization_endpoint,
                metadata.token_endpoint,
                metadata.jwks_uri,
                *(
                    [metadata.end_session_endpoint]
                    if metadata.end_session_endpoint
                    else []
                ),
            ):
                self._config.validate_oidc_url(endpoint, allow_query=True)
            if "S256" not in metadata.code_challenge_methods_supported:
                raise ValueError("Provider does not advertise PKCE S256")
            if not {"RS256", "ES256"}.intersection(
                metadata.id_token_signing_alg_values_supported
            ):
                raise ValueError("Provider has no supported signing algorithm")
            self._client.server_metadata["id_token_signing_alg_values_supported"] = (
                sorted(
                    {"RS256", "ES256"}.intersection(
                        metadata.id_token_signing_alg_values_supported
                    )
                )
            )
            self._metadata = metadata
            self._metadata_until = self._clock() + _CACHE_SECONDS
            return metadata

    def discard(self, binding: str | None) -> None:
        """Remove the current browser transaction without retaining a second index."""
        if binding:
            self._transactions.pop(binding, self._clock())

    async def start(self, return_to: str, previous: str | None) -> tuple[str, str]:
        """Create a provider redirect and opaque cookie bound to the state."""
        self.discard(previous)
        target = validate_return_to(return_to)
        try:
            await self._provider()
            binding = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            authorization = cast(
                "dict[str, Any]",
                await self._client.create_authorization_url(
                    self.callback_url,
                    state=secrets.token_urlsafe(32),
                    nonce=nonce,
                    code_verifier=verifier,
                    response_type="code",
                    response_mode="query",
                ),
            )
            url, state = str(authorization["url"]), str(authorization["state"])
            # The cookie handle and state must both match, even if one is disclosed.
            self._transactions.set(
                binding, LoginTransaction(nonce, verifier, state, target), self._clock()
            )
            return url, binding
        except (httpx2.HTTPError, OAuthError, ValueError) as exc:
            raise OIDCError("unavailable") from exc

    def _consume(
        self, params: Mapping[str, str], binding: str | None
    ) -> LoginTransaction:
        transaction = self._transactions.get(binding or "", self._clock())
        if transaction is None:
            raise OIDCError("expired")
        if not secrets.compare_digest(
            params.get("state", "").encode(), transaction.state.encode()
        ):
            self.discard(binding)
            raise OIDCError("invalid")
        self.discard(binding)
        if "error" in params:
            raise OIDCError("denied")
        if not params.get("code") or (
            "iss" in params and params["iss"] != str(self._config.OIDC_ISSUER_URL)
        ):
            raise OIDCError("invalid")
        return transaction

    async def complete(
        self, params: Mapping[str, str], binding: str | None
    ) -> OIDCIdentity:
        """Consume one attempt before network IO and authorize its signed identity."""
        transaction = self._consume(params, binding)
        try:
            provider = await self._provider()
            token = cast(
                "dict[str, Any]",
                await self._client.fetch_access_token(
                    redirect_uri=self.callback_url,
                    code=params["code"],
                    code_verifier=transaction.verifier,
                ),
            )
            claims = cast(
                "dict[str, Any]",
                await self._client.parse_id_token(
                    token,
                    nonce=transaction.nonce,
                    claims_options={
                        "iss": {"essential": True, "value": provider.issuer},
                        "nonce": {"essential": True, "value": transaction.nonce},
                    },
                    leeway=30,
                ),
            )
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise ValueError("Missing subject")
            return OIDCIdentity(
                provider.issuer, subject, transaction.return_to, token["id_token"]
            )
        except httpx2.HTTPError as exc:
            raise OIDCError("unavailable") from exc
        except (OAuthError, JoseError, ValueError, TypeError, KeyError) as exc:
            raise OIDCError("invalid") from exc

    async def logout_url(self, id_token: str) -> str:
        """Use the discovered logout endpoint; local logout always works offline."""
        try:
            provider = await self._provider()
        except httpx2.HTTPError, OAuthError, ValueError:
            return SIGNED_OUT_PATH
        if not provider.end_session_endpoint:
            return SIGNED_OUT_PATH
        query = urlencode(
            {
                "id_token_hint": id_token,
                "client_id": self._config.OIDC_CLIENT_ID,
                "post_logout_redirect_uri": f"{self._config.APP_URL}{SIGNED_OUT_PATH}",
            }
        )
        endpoint = urlsplit(provider.end_session_endpoint)
        return endpoint._replace(
            query=f"{endpoint.query}&{query}" if endpoint.query else query
        ).geturl()

    def close(self) -> None:
        """Discard pending login material on shutdown."""
        self._transactions.clear()
        self._client.server_metadata.clear()
        self._metadata = None
