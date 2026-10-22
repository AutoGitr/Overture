"""Security utilities - sanitise output before it leaves the process."""

lazy import re
lazy from collections.abc import Generator, Iterable, Mapping, Sequence
lazy from contextlib import contextmanager
lazy from typing import Any, cast
lazy from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

lazy from pydantic import BaseModel

REDACTED = "[REDACTED]"
_OIDC_NAMES = frozenset({"code", "state", "nonce", "code_verifier", "code_challenge"})
_OIDC_VALUES_RE = re.compile(
    r"(?i)(\b(?:code|state|nonce|code_verifier|code_challenge)\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^&,\s;}]+)"
)
_SENSITIVE_NAME_RE = re.compile(
    r"(?i)(^|[_\-.])(?:api[_\-.]?key|apikey|authorization|client[_\-.]?secret|"
    r"password|passwd|pwd|private[_\-.]?key|secret|token|cookie|set[_\-.]?cookie|"
    r"session|jwt|csrf|x[_\-.]?plex[_\-.]?token)(?=$|[_\-.])"
)
_SENSITIVE_PARAM_RE = re.compile(
    r"(?i)([?&][^=\s&;]*(?:api[_-]?key|apikey|authorization|"
    r"client[_-]?secret|password|passwd|pwd|private[_-]?key|secret|token|"
    r"cookie|session|jwt|csrf|x-plex-token)[^=\s&;]*=)[^\&\s]+"
)
_SENSITIVE_KV_RE = re.compile(
    r"(?i)\b([^=\s:,;{}]*(?:api[_-]?key|apikey|authorization|"
    r"client[_-]?secret|password|passwd|pwd|private[_-]?key|secret|token|"
    r"cookie|set-cookie|session|jwt|csrf|x-plex-token)[^=\s:,;{}]*\s*[:=]\s*)"
    r"(\"[^\"]+\"|'[^']+'|[^&,\s;}]+)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)"
    r"((?:bearer|basic)\s+|mediabrowser\s+token=\"?)[^\",\s;}]+\"?"
)
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/@\s]+)@")
_PLEX_DIRECT_URL_RE = re.compile(
    r"(?i)\b(https?://)[^\s/?#\"'<>]+\.plex\.direct(?::\d+)?[^\s\"'<>]*"
)
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)


class Redactor:
    """Immutable secret-redaction policy owned by one application runtime."""

    def __init__(self, secrets: Iterable[str]) -> None:
        self._secrets = tuple(
            sorted(
                {value for value in secrets if value and len(value) >= 8},
                key=len,
                reverse=True,
            )
        )

    def text(self, message: str) -> str:
        """Redact configured secrets and credential-shaped text."""
        return sanitise_error(message, secrets=self._secrets)

    def output(self, value: Any) -> Any:
        """Redact recursively without mutating the input."""
        return sanitise_for_output(value, secrets=self._secrets)


def is_sensitive_field(name: object) -> bool:
    """Return True when a field/header/parameter name usually carries secrets."""
    normalised = str(name).strip().replace(" ", "_")
    return normalised.lower() in _OIDC_NAMES or bool(
        _SENSITIVE_NAME_RE.search(normalised)
    )


def has_sensitive_url_param(value: str | None) -> bool:
    """Return True when *value* contains a credential-like URL parameter."""
    if not value:
        return False
    return bool(_SENSITIVE_PARAM_RE.search(str(value)) or _OIDC_VALUES_RE.search(value))


def strip_sensitive_url(value: str | None) -> str | None:
    """Return None for URLs that contain credential-like query parameters."""
    if has_sensitive_url_param(value):
        return None
    return value


def remove_sensitive_url_params(value: str) -> str:
    """Return *value* with credential-like query parameters removed."""
    parsed = urlsplit(value)
    if not parsed.query:
        return value
    params = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    query = urlencode(
        [(key, param) for key, param in params if not is_sensitive_field(key)],
        doseq=True,
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
    )


def sanitise_error(message: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Replace any secret-looking value in *message* with ``[REDACTED]``."""
    result = str(message)
    for secret in secrets:
        if secret in result:
            result = result.replace(secret, REDACTED)
        encoded = quote(secret, safe="")
        if encoded in result:
            result = result.replace(encoded, REDACTED)
    result = _SENSITIVE_PARAM_RE.sub(rf"\1{REDACTED}", result)
    result = _OIDC_VALUES_RE.sub(rf"\1{REDACTED}", result)
    result = _AUTH_HEADER_RE.sub(rf"\1\2{REDACTED}", result)
    result = _SENSITIVE_KV_RE.sub(rf"\1{REDACTED}", result)
    result = _JWT_RE.sub(REDACTED, result)
    result = _PLEX_DIRECT_URL_RE.sub(rf"\1{REDACTED}.plex.direct", result)
    return _URL_USERINFO_RE.sub(rf"\1{REDACTED}@", result)


@contextmanager
def _cycle_guard(value: object, seen: set[int]) -> Generator[bool]:
    """Mark a container in progress so a self-reference redacts, not recurses."""
    obj_id = id(value)
    if obj_id in seen:
        yield False
        return
    seen.add(obj_id)
    try:
        yield True
    finally:
        seen.discard(obj_id)


def sanitise_for_output(
    value: Any,
    _seen: set[int] | None = None,
    *,
    secrets: tuple[str, ...] = (),
) -> Any:
    """Recursively redact secret-bearing strings and sensitive-keyed values."""
    if isinstance(value, str):
        return sanitise_error(value, secrets=secrets)
    if isinstance(value, bytes | bytearray):
        return sanitise_error(value.decode("utf-8", errors="replace"), secrets=secrets)
    if isinstance(value, BaseException):
        return sanitise_error(str(value), secrets=secrets)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    seen: set[int] = _seen if _seen is not None else set()

    if isinstance(value, Mapping):
        mapping = cast("Mapping[Any, Any]", value)
        with _cycle_guard(mapping, seen) as fresh:
            if not fresh:
                return REDACTED
            return {
                sanitise_error(str(key), secrets=secrets): (
                    REDACTED
                    if is_sensitive_field(key)
                    else sanitise_for_output(item, seen, secrets=secrets)
                )
                for key, item in mapping.items()
            }

    if isinstance(value, tuple):
        items = cast("tuple[Any, ...]", value)
        with _cycle_guard(items, seen) as fresh:
            if not fresh:
                return REDACTED
            return tuple(
                sanitise_for_output(item, seen, secrets=secrets) for item in items
            )

    if isinstance(value, set | frozenset) or (
        isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
    ):
        entries = cast("Iterable[Any]", value)
        with _cycle_guard(entries, seen) as fresh:
            if not fresh:
                return REDACTED
            return [
                sanitise_for_output(item, seen, secrets=secrets) for item in entries
            ]

    return value
