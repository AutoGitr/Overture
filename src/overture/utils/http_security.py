"""HTTP and WebSocket hardening helpers."""

lazy import secrets
lazy from collections.abc import Awaitable, Callable

lazy from fastapi import Request
lazy from starlette.responses import JSONResponse, Response

lazy from ..config import API_PREFIX, Settings, normalise_origin

SESSION_COOKIE = "overture_token"
CSRF_COOKIE = "overture_csrf"
CSRF_HEADER = "X-CSRF-Token"

SIGNED_OUT_PATH = "/?autologin=0"
"""Where a browser lands signed out, without an automatic SSO sign-in."""

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_EXEMPT_PATHS = frozenset({f"{API_PREFIX}/auth/login"})

_CSP_DIRECTIVES = (
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "frame-src https://www.youtube-nocookie.com",
    "form-action 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    "img-src 'self' data: blob: http: https:",
    "media-src 'self' blob:",
    "connect-src 'self'",
)
_CONTENT_SECURITY_POLICY = "; ".join(_CSP_DIRECTIVES)


def new_csrf_token() -> str:
    """Return a high-entropy CSRF token suitable for the double-submit cookie."""
    return secrets.token_urlsafe(32)


def add_security_headers(response: Response, *, app_config: Settings) -> Response:
    """Apply browser security policy to every HTTP response."""
    headers = response.headers
    headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault(
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    )
    if app_config.secure_cookies:
        headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def websocket_origin_allowed(
    *, origin: str, host: str, scheme: str, app_config: Settings
) -> bool:
    """Validate a browser WebSocket origin without trusting proxy headers."""
    if not origin:
        return False
    expected = app_config.APP_URL
    if not expected:
        http_scheme = {"ws": "http", "wss": "https"}.get(scheme)
        if not http_scheme or not host:
            return False
        expected = normalise_origin(f"{http_scheme}://{host}")
    return bool(expected) and normalise_origin(origin) == expected


def validate_mutating_request(request: Request) -> Response | None:
    """Return a rejection response for CSRF-invalid mutating requests, else None."""
    if request.method.upper() not in MUTATING_METHODS:
        return None
    if request.url.path in _CSRF_EXEMPT_PATHS:
        return None
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    header_token = request.headers.get(CSRF_HEADER, "")
    if (
        not cookie_token
        or not header_token
        or not secrets.compare_digest(cookie_token, header_token)
    ):
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    return None


async def security_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    app_config: Settings,
) -> Response:
    """Apply CSRF validation and the browser security policy."""
    rejection = (
        None if app_config.AUTH_MODE == "none" else validate_mutating_request(request)
    )
    response = rejection if rejection is not None else await call_next(request)
    if request.url.path.startswith(f"{API_PREFIX}/auth/"):
        response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith(f"{API_PREFIX}/auth/oidc/"):
            response.headers["Referrer-Policy"] = "no-referrer"
    return add_security_headers(response, app_config=app_config)
