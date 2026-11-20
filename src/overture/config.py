"""Application configuration from the environment and the configuration file."""

lazy import os
lazy import re
lazy import zoneinfo
lazy from collections.abc import Iterable, Mapping
lazy from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
    ip_network,
)
lazy from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
lazy from typing import Annotated, Any, Literal, NamedTuple, Self, cast, override
lazy from urllib.parse import unquote, urlsplit, urlunsplit

lazy from dotenv import dotenv_values
lazy from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    UrlConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
lazy from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
)

lazy from .domain import ServerType
lazy from .passwords import validate_hash
lazy from .utils.file import staged_file
lazy from .utils.hashing import compute_bytes_hash
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


def media_server_identity(server: str, url: str) -> str:
    """Identify a server without storing its address in queued work."""
    return compute_bytes_hash(f"{server}:{url.rstrip('/')}".encode())


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


def _service_url(value: str, setting_name: str) -> str:
    """Normalize a credential-free HTTP URL while preserving a safe base path."""
    candidate = value.strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{setting_name} is not a valid URL") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{setting_name} must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{setting_name} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{setting_name} must not contain a query or fragment")
    if any(part in {".", ".."} for part in unquote(parsed.path).split("/")):
        raise ValueError(f"{setting_name} contains an unsafe path")
    origin = normalise_origin(candidate)
    if not origin:
        raise ValueError(f"{setting_name} is not a valid URL")
    path = parsed.path.rstrip("/")
    return f"{origin}{path}"


def _radarr_url(value: str) -> str:
    """Normalize RADARR_URL."""
    return _service_url(value, "RADARR_URL")


def _sonarr_url(value: str) -> str:
    """Normalize SONARR_URL."""
    return _service_url(value, "SONARR_URL")


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


#: How a server's name is written; its upper-case form names its variables.
_SERVER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*")
#: Every variable that configures media servers starts with this.
_SERVER_VARIABLE_PREFIX = "MEDIA_SERVER"
#: The fields each server's ``MEDIA_SERVER_<NAME>_<FIELD>`` variables set.
_SERVER_FIELDS = (
    "type",
    "url",
    "api_key",
    "verify_tls",
    "path_map",
    "collections_path",
)


class PathMapping(NamedTuple):
    """A folder as the media server reports it, and where Overture sees it."""

    server: str
    local: str


def _pure_server_path(path: str) -> PurePath:
    """Interpret a server path by its syntax, independent of Overture's OS."""
    return (
        PureWindowsPath(path)
        if "\\" in path or path[1:2] == ":"
        else (PurePosixPath(path))
    )


def _path_map(value: object) -> object:
    """Split ``server=local`` pairs, separated by commas, longest server path first."""
    if not isinstance(value, str):
        return value
    mappings: list[PathMapping] = []
    for entry in filter(None, (part.strip() for part in value.split(","))):
        server, separator, local = (side.strip() for side in entry.partition("="))
        if not separator or not server or not local:
            raise ValueError(
                f"PATH_MAP entry {entry!r} must be written server_path=local_path"
            )
        if not Path(local).is_absolute():
            raise ValueError(f"PATH_MAP local path {local!r} must be absolute")
        mappings.append(PathMapping(server, local))
    return tuple(
        sorted(mappings, key=lambda mapping: len(mapping.server), reverse=True)
    )


class MediaServerConfig(BaseModel):
    """One media server Overture talks to, as its variables configure it."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    #: As written in MEDIA_SERVERS; its lower-case form identifies the server.
    name: Annotated[str, Field(pattern=_SERVER_NAME.pattern, max_length=40)]
    type: Annotated[ServerType, BeforeValidator(_lowercase)]
    url: str
    api_key: SecretStr
    verify_tls: bool = True
    #: Where Overture sees the folders the server reports, longest first.
    path_map: Annotated[tuple[PathMapping, ...], BeforeValidator(_path_map)] = ()
    #: Jellyfin's collections metadata folder, mounted into Overture, where it
    #: writes each collection's theme.mp3.
    collections_path: Path | None = None

    _plex_secure_origin: str | None = PrivateAttr(default=None)

    @field_validator("url")
    @classmethod
    def normalise_url(cls, value: str) -> str:
        """Require a credential-free HTTP URL, keeping a base path."""
        url = _service_url(value, "URL")
        if not url:
            raise ValueError("URL is required")
        return url

    @field_validator("api_key")
    @classmethod
    def require_api_key(cls, value: SecretStr) -> SecretStr:
        """Require a token or API key."""
        if not value.get_secret_value():
            raise ValueError("API_KEY is required")
        return value

    def variable(self, field: str) -> str:
        """Return the variable that sets *field* of this server."""
        return _server_variable(self.name, field)

    @property
    def key(self) -> str:
        """The name the database identifies the server by."""
        return self.name.lower()

    @property
    def title(self) -> str:
        """How the server is named to users."""
        return self.name.replace("_", " ")

    @property
    def identity(self) -> str:
        """Identify the server by kind and address, which a rename keeps."""
        return media_server_identity(self.type, self.url)

    def local_path(self, path: str) -> str:
        """Return where Overture sees a path the server reports."""
        for mapping in self.path_map:
            prefix = _pure_server_path(mapping.server)
            try:
                rest = type(prefix)(path).relative_to(prefix).parts
            except ValueError:
                continue
            return str(Path(mapping.local).joinpath(*rest))
        return path

    def is_trusted_url(self, url: str) -> bool:
        """Return whether *url* is this server's configured or verified origin."""
        origin = normalise_origin(url)
        return bool(origin) and origin in {
            normalise_origin(self.url),
            self._plex_secure_origin,
        }

    def plex_direct_origin(self, url: str) -> str:
        """Return *url* as a bare plex.direct HTTPS origin, or ``""``.

        Only a credential-free, path-free HTTPS URL in Plex's connection
        domain qualifies, and only for a Plex server.
        """
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError:
            return ""
        if (
            self.type is not ServerType.PLEX
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

    def verify_tls_for(self, url: str | None = None) -> bool:
        """Return the TLS policy for a request to this server at *url*."""
        origin = normalise_origin(url or self.url)
        if origin and origin == self._plex_secure_origin:
            return True
        if url is not None and not self.is_trusted_url(url):
            return True
        return self.verify_tls


def _server_value(variables: Mapping[str, str], name: str) -> str | None:
    value = variables.get(name)
    return value or None


def _server_variable(name: str, field: str) -> str:
    """Return the variable that sets *field* of the server named *name*."""
    return f"{_SERVER_VARIABLE_PREFIX}_{name.upper()}_{field.upper()}"


def _configured_server(name: str, variables: Mapping[str, str]) -> MediaServerConfig:
    """Build the server named *name* from its ``MEDIA_SERVER_<NAME>_*`` variables."""
    values = {
        field: value
        for field in _SERVER_FIELDS
        if (value := _server_value(variables, _server_variable(name, field)))
        is not None
    }
    if "type" not in values:
        raise ValueError(
            f"{_server_variable(name, 'type')} is required and must be 'plex', "
            "'jellyfin' or 'emby'"
        )
    try:
        return MediaServerConfig.model_validate({"name": name, **values})
    except ValidationError as exc:
        problems = "; ".join(
            (
                _server_variable(name, str(error["loc"][0]))
                if error["loc"]
                else "MEDIA_SERVERS"
            )
            + ": "
            + error["msg"].removeprefix("Value error, ")
            for error in exc.errors()
        )
        raise ValueError(f"Media server {name!r} is misconfigured: {problems}") from exc


def parse_media_servers(variables: Mapping[str, str]) -> tuple[MediaServerConfig, ...]:
    """Build the media servers MEDIA_SERVERS names, the lead first.

    Each name is configured by ``MEDIA_SERVER_<NAME>_*`` variables; ``none``
    runs without a media server.

    Raises:
        ValueError: When the servers are missing, repeated or misconfigured.
    """
    listed = _server_value(variables, "MEDIA_SERVERS")
    if not listed:
        raise ValueError(
            "MEDIA_SERVERS is required: list the names of your media servers, "
            "each configured by MEDIA_SERVER_<NAME>_TYPE, _URL and _API_KEY, "
            "or set it to 'none'"
        )
    if listed.strip().lower() == "none":
        return ()
    names = [part.strip() for part in listed.split(",") if part.strip()]
    keys = [name.lower() for name in names]
    if repeated := sorted({key for key in keys if keys.count(key) > 1}):
        raise ValueError(f"MEDIA_SERVERS names {', '.join(repeated)} more than once")
    servers: list[MediaServerConfig] = []
    for name in names:
        if not _SERVER_NAME.fullmatch(name):
            raise ValueError(
                f"MEDIA_SERVERS name {name!r} must start with a letter and hold only "
                "letters, digits and single underscores"
            )
        servers.append(_configured_server(name, variables))
    return tuple(servers)


def _is_server_variable(name: str) -> bool:
    return name.startswith(_SERVER_VARIABLE_PREFIX)


class _MediaServerVariables(PydanticBaseSettingsSource):
    """Every media-server variable the other sources hold.

    A server's variables are named after it, so the settings model cannot
    declare them as fields for the environment, file and secret sources to
    read; this source collects them from each, in the same priority.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        sources: Iterable[PydanticBaseSettingsSource],
    ) -> None:
        super().__init__(settings_cls)
        self._sources = tuple(sources)

    @override
    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        """Answer no field; :meth:`__call__` reads the variables."""
        return None, field_name, False

    @override
    def __call__(self) -> dict[str, Any]:
        """Return the variables, a higher-priority source winning."""
        found: dict[str, str] = {}
        for source in reversed(self._sources):
            found.update(_variables_of(source))
        return found


def _variables_of(source: PydanticBaseSettingsSource) -> dict[str, str]:
    """Return the media-server variables one source holds, upper-cased."""
    if isinstance(source, EnvSettingsSource):
        entries: Iterable[tuple[str, str | None]] = source.env_vars.items()
    elif isinstance(source, SecretsSettingsSource):
        folders = source.secrets_dir
        entries = (
            (path.name, path.read_text().strip())
            for folder in (folders if isinstance(folders, (list, tuple)) else [folders])
            if folder is not None and Path(str(folder)).is_dir()
            for path in Path(str(folder)).iterdir()
            if path.is_file() and _is_server_variable(path.name.upper())
        )
    else:
        return {}
    return {
        name.upper(): value
        for name, value in entries
        if value and _is_server_variable(name.upper())
    }


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
    # see, so the field has a default: an empty one, which build_media_servers
    # reports as missing.
    #: The media servers in the order MEDIA_SERVERS lists them, the first
    #: leading; none when it is ``none``: Overture runs on the catalog and TMDB.
    MEDIA_SERVERS: Annotated[tuple[MediaServerConfig, ...], NoDecode] = cast(
        "tuple[MediaServerConfig, ...]", ""
    )

    TMDB_READ_ACCESS_TOKEN: SecretStr = SecretStr("")
    MDBLIST_API_KEY: SecretStr = SecretStr("")
    RADARR_URL: Annotated[str, AfterValidator(_radarr_url)] = ""
    RADARR_API_KEY: SecretStr = SecretStr("")
    RADARR_VERIFY_TLS: bool = True
    SONARR_URL: Annotated[str, AfterValidator(_sonarr_url)] = ""
    SONARR_API_KEY: SecretStr = SecretStr("")
    SONARR_VERIFY_TLS: bool = True
    #: Where a failed run is announced: one webhook or Apprise API URL, which
    #: may hold its own credentials.
    NOTIFY_URL: SecretStr = SecretStr("")

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
    # Above these, image hosts and YouTube rate-limit or block the address.
    ART_DOWNLOAD_WORKERS: Annotated[int, Field(ge=1, le=10)] = 1
    THEME_DOWNLOAD_WORKERS: Annotated[int, Field(ge=1, le=4)] = 1

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read the media servers' variables from every source as well."""
        return (
            init_settings,
            _MediaServerVariables(
                settings_cls, (env_settings, dotenv_settings, file_secret_settings)
            ),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @model_validator(mode="before")
    @classmethod
    def build_media_servers(cls, data: object) -> object:
        """Build MEDIA_SERVERS from the variables naming and configuring them."""
        if not isinstance(data, dict):
            return data
        values = cast("dict[str, object]", data)
        variables = {
            name.upper(): str(value)
            for name, value in values.items()
            if _is_server_variable(name.upper())
            and isinstance(value, str | bool | int | Path)
            and value != ""
        }
        listed = values.get("MEDIA_SERVERS")
        others = {
            name: value
            for name, value in values.items()
            if not _is_server_variable(name.upper())
        }
        # Servers already built, as a dumped Settings holds them, stand as they are.
        if listed is not None and not isinstance(listed, str):
            return others | {"MEDIA_SERVERS": listed}
        return others | {"MEDIA_SERVERS": parse_media_servers(variables)}

    @field_validator("NOTIFY_URL")
    @classmethod
    def validate_notify_url(cls, value: SecretStr) -> SecretStr:
        """Accept an absolute HTTP or HTTPS URL, or none."""
        url = value.get_secret_value().strip()
        if url and urlsplit(url).scheme.lower() not in {"http", "https"}:
            raise ValueError("NOTIFY_URL must be an absolute HTTP or HTTPS URL")
        return SecretStr(url)

    @field_validator("OIDC_ISSUER_URL", mode="before")
    @classmethod
    def empty_issuer(cls, value: object) -> object:
        """An empty environment entry leaves optional OIDC disabled."""
        return None if value == "" else value

    def secret_values(self) -> list[str]:
        """Return every configured secret, which the log redacts by value."""
        values = [
            *self.model_dump(exclude={"MEDIA_SERVERS"}).values(),
            *(server.api_key for server in self.MEDIA_SERVERS),
        ]
        return [
            value.get_secret_value()
            for value in values
            if isinstance(value, SecretStr) and value.get_secret_value()
        ]

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
        """Reject partially configured service credentials."""
        if bool(self.RADARR_URL) != bool(self.RADARR_API_KEY.get_secret_value()):
            raise ValueError("RADARR_URL and RADARR_API_KEY are required together")
        if bool(self.SONARR_URL) != bool(self.SONARR_API_KEY.get_secret_value()):
            raise ValueError("SONARR_URL and SONARR_API_KEY are required together")
        return self

    def is_trusted_proxy(self, address: IPv4Address | IPv6Address) -> bool:
        """Return whether an address belongs to an explicitly trusted proxy."""
        return any(address in network for network in self.TRUSTED_PROXY_CIDRS)

    @property
    def secure_cookies(self) -> bool:
        """True when APP_URL uses https; auth cookies receive the Secure flag."""
        return self.APP_URL.startswith("https://")

    def is_trusted_media_server_url(self, url: str) -> bool:
        """Return whether *url* is a configured or verified server origin."""
        return any(server.is_trusted_url(url) for server in self.MEDIA_SERVERS)

    def media_server_verify_tls(self, url: str | None) -> bool:
        """Return the TLS policy for *url*: its server's, or verified elsewhere."""
        if url is None:
            return True
        return next(
            (
                server.verify_tls_for(url)
                for server in self.MEDIA_SERVERS
                if server.is_trusted_url(url)
            ),
            True,
        )

    @property
    def tmdb_configured(self) -> bool:
        """Return whether TMDB access is configured."""
        return bool(self.TMDB_READ_ACCESS_TOKEN)

    @property
    def mdblist_configured(self) -> bool:
        """Return whether MDBList access is configured."""
        return bool(self.MDBLIST_API_KEY)

    @property
    def radarr_configured(self) -> bool:
        """Return whether Radarr access is configured."""
        return bool(self.RADARR_URL and self.RADARR_API_KEY)

    @property
    def sonarr_configured(self) -> bool:
        """Return whether Sonarr access is configured."""
        return bool(self.SONARR_URL and self.SONARR_API_KEY)

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
    with staged_file(
        path.parent, mode=previous.st_mode & 0o640 if previous else 0o640
    ) as staged:
        if os.name == "posix":
            os.chown(
                staged.path,
                previous.st_uid if previous else -1,
                previous.st_gid if previous else path.parent.stat().st_gid,
            )
        staged.stream.write("".join(lines).encode())
        staged.place(path)
