"""Application configuration from the environment and the configuration file."""

lazy import os
lazy import tempfile
lazy import zoneinfo
lazy from collections.abc import Mapping
lazy from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
lazy from pathlib import Path
lazy from typing import Annotated, Literal, Self, cast
lazy from urllib.parse import unquote, urlsplit, urlunsplit

lazy from dotenv import dotenv_values
lazy from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BeforeValidator,
    Field,
    PrivateAttr,
    SecretStr,
    UrlConstraints,
    field_validator,
    model_validator,
)
lazy from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

lazy from .domain import ServerType
lazy from .passwords import validate_hash
lazy from .utils.ssrf import LOOPBACK_HOSTS

API_PREFIX = "/api"
"""Path prefix of every REST endpoint; the frontend owns every other path."""

HOST = "127.0.0.1"
"""Default native listening address."""

PORT = 5885
"""Default listening port."""

CONFIG_DIR = Path("/var/lib/overture")
"""Default native directory for the database, backups and caches."""

CONFIG_FILE = Path("/etc/overture/overture.env")
"""Default native configuration file."""

SECRETS_DIR = Path("/run/secrets")
"""Where Docker Compose mounts secrets; a file named like a setting supplies it."""

PLEX_DIRECT_DOMAIN = "plex.direct"
"""The domain of Plex's HTTPS connection hosts."""

type LogLevel = Literal["debug", "info", "warning", "error", "critical"]
type ProxyNetworks = tuple[IPv4Network | IPv6Network, ...]
type AuthMode = Literal["password", "oidc", "both", "none"]


def in_plex_direct_domain(hostname: str) -> bool:
    """Return whether *hostname* is Plex's HTTPS connection domain or a host in it."""
    hostname = hostname.lower().rstrip(".")
    return hostname == PLEX_DIRECT_DOMAIN or hostname.endswith(f".{PLEX_DIRECT_DOMAIN}")


def is_plex_direct_host(hostname: str) -> bool:
    """Return whether *hostname* is a host in Plex's HTTPS connection domain."""
    return in_plex_direct_domain(hostname) and (
        hostname.lower().rstrip(".") != PLEX_DIRECT_DOMAIN
    )


def normalise_origin(value: str) -> str:
    """Return scheme://host[:port] for a URL/origin string, or '' if unparseable."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not scheme or not hostname or parsed.username or parsed.password:
        return ""
    if port == {"http": 80, "https": 443}.get(scheme):
        port = None
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((scheme, netloc, "", "", ""))


def _password_hash(value: SecretStr) -> SecretStr:
    """Require the application's Argon2id encoding."""
    return SecretStr(validate_hash(value.get_secret_value()))


def _timezone_name(value: str) -> str:
    """Default blank timezones to UTC and reject unknown IANA names."""
    value = (value or "").strip() or "UTC"
    try:
        zoneinfo.ZoneInfo(value)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise ValueError(f"TZ {value!r} is not a valid IANA timezone name.") from exc
    return value


def _app_url(value: str) -> str:
    """Normalize APP_URL to a bare http(s) origin."""
    if not value.strip():
        return ""
    origin = normalise_origin(value)
    if not origin or not origin.startswith(("http://", "https://")):
        raise ValueError(
            "APP_URL must be an absolute URL with an http or https scheme, "
            "e.g. https://overture.example.com"
        )
    return origin


def _media_server_url(value: str) -> str:
    """Normalize a credential-free HTTP URL while preserving a safe base path."""
    candidate = value.strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("MEDIA_SERVER_URL is not a valid URL") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MEDIA_SERVER_URL must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("MEDIA_SERVER_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("MEDIA_SERVER_URL must not contain a query or fragment")
    if any(part in {".", ".."} for part in unquote(parsed.path).split("/")):
        raise ValueError("MEDIA_SERVER_URL contains an unsafe path")
    origin = normalise_origin(candidate)
    if not origin:
        raise ValueError("MEDIA_SERVER_URL is not a valid URL")
    path = parsed.path.rstrip("/")
    return f"{origin}{path}"


def _proxy_networks(value: object) -> object:
    """Split a comma-separated trusted-proxy allowlist into networks."""
    if not isinstance(value, str):
        return value
    networks: list[IPv4Network | IPv6Network] = []
    for candidate in filter(None, (part.strip() for part in value.split(","))):
        try:
            networks.append(ip_network(candidate, strict=False))
        except ValueError as exc:
            raise ValueError(
                f"TRUSTED_PROXY_CIDRS contains an invalid network: {candidate!r}"
            ) from exc
    return tuple(dict.fromkeys(networks))


def _lowercase(value: object) -> object:
    """Accept environment values in any case."""
    return value.strip().lower() if isinstance(value, str) else value


def _media_server(value: object) -> object:
    """Require a media server kind, in any case."""
    if not value:
        raise ValueError(
            "MEDIA_SERVER is required and must be 'plex', 'jellyfin', or 'emby'."
        )
    return _lowercase(value)


class RuntimeSettings(BaseSettings):
    """Installation options that can be loaded before credentials exist."""

    OVERTURE_CONFIG_DIR: Path = CONFIG_DIR
    OVERTURE_HOST: str = HOST
    OVERTURE_PORT: Annotated[int, Field(ge=1, le=65535)] = PORT

    @field_validator("OVERTURE_HOST")
    @classmethod
    def listening_address(cls, value: str) -> str:
        """Bind only to explicit addresses or the localhost name."""
        if value == "localhost":
            return value
        try:
            return str(ip_address(value))
        except ValueError as exc:
            raise ValueError(
                "OVERTURE_HOST must be an IP address or localhost"
            ) from exc

    model_config = SettingsConfigDict(
        # Compose passes unset optional variables as empty strings.
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
        validate_default=True,
    )


def configuration_file() -> Path:
    """Select a configuration file independently of the working directory."""
    return Path(os.environ.get("OVERTURE_CONFIG_FILE", str(CONFIG_FILE)))


class Settings(RuntimeSettings):
    """Load and validate application configuration from environment variables."""

    AUTH_MODE: Annotated[AuthMode, BeforeValidator(_lowercase)] = "password"
    APP_PASSWORD_HASH: Annotated[SecretStr, AfterValidator(_password_hash)] = SecretStr(
        ""
    )
    SESSION_EXPIRY_DAYS: Annotated[int, Field(gt=0)] = 7

    OIDC_ISSUER_URL: (
        Annotated[AnyHttpUrl, UrlConstraints(preserve_empty_path=True)] | None
    ) = None
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: SecretStr = SecretStr("")
    OIDC_DISPLAY_NAME: Annotated[str, Field(min_length=1, max_length=80)] = (
        "Sign in with SSO"
    )
    OIDC_AUTO_LOGIN: bool = False

    # Required. Settings come from the environment, which type checkers cannot
    # see, so the field has a default: an empty one, which validate_default
    # passes to _media_server to report as missing.
    MEDIA_SERVER: Annotated[ServerType, BeforeValidator(_media_server)] = cast(
        "ServerType", ""
    )
    MEDIA_SERVER_URL: Annotated[str, AfterValidator(_media_server_url)] = ""
    MEDIA_SERVER_API_KEY: SecretStr = SecretStr("")
    MEDIA_SERVER_VERIFY_TLS: bool = True

    TMDB_API_KEY: SecretStr = SecretStr("")

    # Canonical browser origin. This controls secure cookies and WebSocket origin
    # checks; it does not grant trust to any reverse proxy.
    APP_URL: Annotated[str, AfterValidator(_app_url)] = ""
    TRUSTED_PROXY_CIDRS: Annotated[
        ProxyNetworks, NoDecode, BeforeValidator(_proxy_networks)
    ] = ()

    LOG_LEVEL: Annotated[LogLevel, BeforeValidator(_lowercase)] = "info"
    # Colour each line's time, level and component. Container log viewers
    # render the ANSI codes; turn it off for a plain-text log destination.
    LOG_COLOUR: bool = True
    # Standard IANA timezone used for logs and cron schedules.
    TZ: Annotated[str, AfterValidator(_timezone_name)] = "UTC"
    PHASH_WORKERS: Annotated[int, Field(ge=1, le=32)] = 1
    ART_DOWNLOAD_WORKERS: Annotated[int, Field(ge=1, le=16)] = 1
    THEME_DOWNLOAD_WORKERS: Annotated[int, Field(ge=1, le=16)] = 1

    _plex_secure_origin: str | None = PrivateAttr(default=None)

    @field_validator("OIDC_ISSUER_URL", mode="before")
    @classmethod
    def empty_issuer(cls, value: object) -> object:
        """An empty environment entry leaves optional OIDC disabled."""
        return None if value == "" else value

    @property
    def oidc_enabled(self) -> bool:
        """Whether the configured identity provider may authenticate users."""
        return self.AUTH_MODE in {"oidc", "both"}

    @property
    def password_enabled(self) -> bool:
        """Whether password authentication may authenticate users."""
        return self.AUTH_MODE in {"password", "both"}

    def validate_oidc_url(self, value: str, *, allow_query: bool = False) -> str:
        """Validate a trusted OIDC URL without changing issuer path semantics."""
        parsed = urlsplit(value)
        if (
            not normalise_origin(value)
            or (parsed.query and not allow_query)
            or parsed.fragment
            or "\\" in value
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("OIDC URLs must be absolute, credential-free URLs")
        if parsed.scheme == "https":
            return value
        if parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS:
            return value
        raise ValueError("OIDC requires HTTPS (except HTTP on loopback)")

    @model_validator(mode="after")
    def validate_authentication(self) -> Self:
        """Reject incomplete or unsafe authentication configuration."""
        oidc_credentials = (
            self.OIDC_ISSUER_URL is not None,
            bool(self.OIDC_CLIENT_ID.strip()),
            bool(self.OIDC_CLIENT_SECRET.get_secret_value()),
        )
        if self.oidc_enabled:
            if not all(oidc_credentials):
                raise ValueError(
                    "OIDC_ISSUER_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET "
                    "are required when OIDC is enabled"
                )
            self.validate_oidc_url(self.APP_URL)
            self.validate_oidc_url(str(self.OIDC_ISSUER_URL))
        else:
            if any(oidc_credentials) and not all(oidc_credentials):
                raise ValueError(
                    "OIDC_ISSUER_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET "
                    "are required together"
                )
            if self.AUTH_MODE != "none" and self.OIDC_AUTO_LOGIN:
                raise ValueError("OIDC_AUTO_LOGIN requires OIDC configuration")

        if self.password_enabled and not self.APP_PASSWORD_HASH.get_secret_value():
            raise ValueError(
                "APP_PASSWORD_HASH is required when password authentication is enabled"
            )
        return self

    @model_validator(mode="after")
    def validate_service_pairs(self) -> Self:
        """Reject partially configured media-server credentials."""
        missing = [
            name
            for name in ("MEDIA_SERVER_URL", "MEDIA_SERVER_API_KEY")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                "Media Server Configuration Error: missing required setting(s): "
                + ", ".join(missing)
            )
        return self

    def is_trusted_proxy(self, value: str) -> bool:
        """Return whether an address belongs to an explicitly trusted proxy."""
        try:
            address = ip_address(value)
        except ValueError:
            return False
        return any(address in network for network in self.TRUSTED_PROXY_CIDRS)

    @property
    def secure_cookies(self) -> bool:
        """True when APP_URL uses https; auth cookies receive the Secure flag."""
        return self.APP_URL.startswith("https://")

    @property
    def is_plex(self) -> bool:
        """Return whether Plex is the active media server."""
        return self.MEDIA_SERVER == ServerType.PLEX

    def is_trusted_media_server_url(self, url: str) -> bool:
        """Return whether a URL has a configured or verified server origin."""
        origin = normalise_origin(url)
        return bool(origin) and origin in {
            normalise_origin(self.MEDIA_SERVER_URL),
            self._plex_secure_origin,
        }

    def plex_direct_origin(self, url: str) -> str:
        """Return *url* as a bare plex.direct HTTPS origin, or ``""``.

        Only a credential-free, path-free HTTPS URL in Plex's connection
        domain qualifies, and only while Plex is the active media server.
        """
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError:
            return ""
        if (
            not self.is_plex
            or parsed.scheme.lower() != "https"
            or not is_plex_direct_host(parsed.hostname or "")
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return ""
        return normalise_origin(url)

    def trust_plex_secure_url(self, url: str) -> str:
        """Record the exact verified plex.direct origin used by this process."""
        origin = self.plex_direct_origin(url)
        if not origin:
            raise ValueError("Plex returned an invalid secure connection URL")
        self._plex_secure_origin = origin
        return origin

    def media_server_verify_tls(self, url: str | None = None) -> bool:
        """Return the TLS policy for a trusted media-server request URL."""
        target_url = url or self.MEDIA_SERVER_URL
        origin = normalise_origin(target_url)
        if origin and origin == self._plex_secure_origin:
            return True
        if url is not None and not self.is_trusted_media_server_url(url):
            return True
        return self.MEDIA_SERVER_VERIFY_TLS

    @property
    def tmdb_configured(self) -> bool:
        """Return whether TMDB access is configured."""
        return bool(self.TMDB_API_KEY)

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        """Return the configured timezone object."""
        return zoneinfo.ZoneInfo(self.TZ)


def read_configuration(path: Path) -> dict[str, str]:
    """Read the configuration file's entries as written, for setup to edit."""
    if not path.exists():
        return {}
    return {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }


def load_configuration[T: RuntimeSettings](
    model: type[T], path: Path | None = None
) -> T:
    """Load the environment, then the configuration file, then Compose secrets."""
    # BaseSettings takes source options at runtime; type checkers see only fields.
    return model(
        _env_file=path or configuration_file(),  # pyright: ignore[reportCallIssue]
        _secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None,  # pyright: ignore[reportCallIssue]
    )


def write_configuration(path: Path, values: Mapping[str, str]) -> None:
    """Replace the file with literal entries once they have reached the disk."""
    lines = [
        "{}='{}'\n".format(key, value.replace("\\", "\\\\").replace("'", "\\'"))
        for key, value in sorted(values.items())
    ]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    previous = path.stat() if path.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix=".overture-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", newline="\n") as stream:
            temporary_path.chmod(previous.st_mode & 0o640 if previous else 0o640)
            if os.name == "posix":
                os.chown(
                    temporary_path,
                    previous.st_uid if previous else -1,
                    previous.st_gid if previous else path.parent.stat().st_gid,
                )
            stream.writelines(lines)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
