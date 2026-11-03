"""Redaction of credential-shaped text, where text leaves the process.

Two boundaries call it, and nothing else needs to: ``PublicText`` fields,
whenever a schema serialises them (responses, events, stored job rows), and the
log formatter, which also knows the configured secrets' values. Artwork links
are cleaned before they are stored, by ``remove_sensitive_url_params``.
"""

lazy import re
lazy from collections.abc import Iterable
lazy from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

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
    """The log's redaction policy, which also knows the configured secrets."""

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


def _sensitive_param(name: str) -> bool:
    """Return whether a URL query parameter's name says it carries a credential."""
    normalised = name.strip().replace(" ", "_")
    return normalised.lower() in _OIDC_NAMES or bool(
        _SENSITIVE_NAME_RE.search(normalised)
    )


def remove_sensitive_url_params(value: str) -> str:
    """Return *value* with credential-like query parameters removed."""
    parsed = urlsplit(value)
    if not parsed.query:
        return value
    params = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    query = urlencode(
        [(key, param) for key, param in params if not _sensitive_param(key)],
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
