"""One log line per HTTP request, and the boundary for unhandled errors."""

lazy import logging
lazy import re
lazy import secrets
lazy import time
lazy from collections.abc import Awaitable, Callable
lazy from urllib.parse import quote

lazy from fastapi import Request, Response
lazy from starlette.responses import JSONResponse

lazy from ..config import API_PREFIX, Settings
lazy from .http_security import MUTATING_METHODS, add_security_headers

logger = logging.getLogger("overture.http")

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_QUIET_PATHS = {f"{API_PREFIX}/health", f"{API_PREFIX}/ready"}
_QUIET_API_PARTS = (
    "/image/",
    "/local-image/",
    "/provider-art",
    "/provider-poster",
)


def request_log_level(method: str, path: str, status_code: int) -> int:
    """Rank a request by what it tells someone reading the log.

    Server failures are errors. Refused requests (forbidden, rate limited) are
    warnings, as they can signal misuse. Changes and other client errors are
    info. Reads, probes, images and the frontend's files are routine: debug.
    """
    if status_code >= 500:
        return logging.ERROR
    if status_code in {403, 429}:
        return logging.WARNING
    if (
        path in _QUIET_PATHS
        or not path.startswith(f"{API_PREFIX}/")
        or any(part in path for part in _QUIET_API_PARTS)
    ):
        return logging.DEBUG
    if status_code >= 400 or method in MUTATING_METHODS:
        return logging.INFO
    return logging.DEBUG


def _request_id(request: Request) -> str:
    """Return the caller's request ID when it is a plain token, else a new one.

    A reverse proxy's ID links its logs to Overture's; any other value is
    replaced, so the header can never inject text into a log line.
    """
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _REQUEST_ID_RE.fullmatch(supplied) else secrets.token_hex(4)


async def request_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    app_config: Settings,
) -> Response:
    """Log each request once, without its query string or body.

    Every response carries an ``X-Request-ID``, which the log line names for
    failed requests. As the outermost
    middleware this is also the error boundary: an unhandled exception is
    logged here, once, with its traceback, and answered with a sanitised 500.
    """
    request_id = _request_id(request)
    started = time.perf_counter()
    failure: Exception | None = None
    try:
        response = await call_next(request)
    except Exception as exc:
        failure = exc
        response = add_security_headers(
            JSONResponse({"detail": "Internal server error"}, status_code=500),
            app_config=app_config,
        )
    response.headers[REQUEST_ID_HEADER] = request_id

    status = response.status_code
    logger.log(
        request_log_level(request.method, request.url.path, status),
        "%s %s -> %d in %.1f ms%s",
        request.method,
        # Percent-encoded again, so a decoded control character cannot forge
        # a log line.
        quote(request.url.path),
        status,
        (time.perf_counter() - started) * 1000,
        f" (request {request_id})" if status >= 400 else "",
        exc_info=failure,
    )
    return response
