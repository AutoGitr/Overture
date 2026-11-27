"""Overture - Application entry point."""

lazy import asyncio
lazy import logging
lazy import sys
lazy from collections.abc import AsyncGenerator, Callable, Mapping
lazy from contextlib import asynccontextmanager
lazy from functools import partial
lazy from pathlib import Path
lazy from typing import Any, cast

lazy from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
lazy from fastapi.exceptions import RequestValidationError
lazy from fastapi.openapi.docs import get_swagger_ui_html
lazy from fastapi.routing import APIRoute
lazy from fastapi.staticfiles import StaticFiles
lazy from pydantic import SecretStr
lazy from starlette.exceptions import HTTPException as StarletteHTTPException
lazy from starlette.responses import HTMLResponse, JSONResponse

lazy from .config import API_PREFIX, Settings
lazy from .dependencies import RuntimeDep
lazy from .media_servers.errors import MediaServerError
lazy from .routers.art import router as art_router
lazy from .routers.asset_manager import router as asset_manager_router
lazy from .routers.auth import authenticated_router
lazy from .routers.auth import router as auth_router
lazy from .routers.backup import router as backup_router
lazy from .routers.bulk_assets import router as bulk_assets_router
lazy from .routers.catalog import router as catalog_router
lazy from .routers.collections import groups_router as collection_groups_router
lazy from .routers.collections import router as collections_router
lazy from .routers.job_snapshots import router as job_snapshots_router
lazy from .routers.library import router as library_router
lazy from .routers.library_filters import router as library_filters_router
lazy from .routers.media_server import router as media_server_router
lazy from .routers.notifications import router as notifications_router
lazy from .routers.realtime import router as realtime_router
lazy from .routers.responses import declare_framework_answers
lazy from .routers.server_audit import router as server_audit_router
lazy from .routers.settings import router as settings_router
lazy from .routers.stats import router as stats_router
lazy from .routers.sync import router as sync_router
lazy from .routers.themes import router as themes_router
lazy from .routers.tmdb import router as tmdb_router
lazy from .runtime import RuntimeServices, build_runtime
lazy from .runtime_paths import FRONTEND_DIR
lazy from .schemas.app import HealthResponse, ReadinessResponse
lazy from .schemas.common import (
    ErrorResponse,
    ValidationErrorResponse,
    ValidationIssue,
)
lazy from .utils.errors import PublicServiceError
lazy from .utils.http_security import (
    BUILD_ASSETS_PATH,
    SESSION_COOKIE,
    is_backend_path,
    security_middleware,
    websocket_origin_allowed,
)
lazy from .utils.request_logging import request_logging_middleware
lazy from .utils.time import utc_now
lazy from .version import APP_VERSION
lazy from .ws.resync import send_client_resync

logger = logging.getLogger(__name__)

docs_router = authenticated_router()
health_router = APIRouter(tags=["health"])
websocket_router = APIRouter()


#: The largest request body a route reads unless it allows more, as the image
#: upload does: several times the largest JSON a request needs, a collection's
#: 10,000 member IDs, and far below what would strain memory.
MAX_REQUEST_BODY = 1024 * 1024


#: What each group of the API's operations is about, in the order docs list them.
_TAGS = {
    "auth": "Signing in, sessions, OIDC and API keys.",
    "settings": "Overture's settings and what its media servers can do.",
    "library": "Titles and seasons, their art and themes, as the library holds them.",
    "library-filters": "Saved filters and the values they test.",
    "art": "Choosing, uploading and removing posters and backgrounds.",
    "themes": "Choosing, searching for and removing theme songs.",
    "tmdb": "Looking up titles, people and franchises on TMDB.",
    "catalog": "OvertureDB: its catalog, drafts and contributions.",
    "collections": (
        "Collections, their groups, sets, criteria and presets, art and themes."
    ),
    "bulk": "Assets runs: art and themes for many titles at once, and schedules.",
    "sync": "Library syncs and their schedules.",
    "media-server": "The media servers: their libraries, links and health.",
    "server-audit": "Comparing what the servers hold with what Overture chose.",
    "asset-manager": "Files in the media folders that Overture manages.",
    "job-snapshots": "What running and finished jobs did.",
    "notifications": "Where Overture sends notices, and which.",
    "stats": "Counts of what the library holds and lacks.",
    "backups": "Database backups: taking, listing and restoring them.",
    "realtime": "The WebSocket that pushes changes to the browser.",
    "health": "Whether Overture is up and ready.",
}


def _operation_id(route: APIRoute) -> str:
    """Return stable semantic OpenAPI operation IDs."""
    return route.name


def _openapi(build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """The app's schema, with what every route answers whatever it declares."""
    return declare_framework_answers(build())


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Start and stop the configured runtime services."""
    runtime: RuntimeServices = app.state.runtime
    try:
        await runtime.start()
        yield
    finally:
        await runtime.stop()


def create_app(
    runtime: RuntimeServices | None = None,
    *,
    app_settings: Settings | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    """Create a FastAPI application with an explicit runtime container."""
    runtime = (
        runtime if runtime is not None else build_runtime(app_settings=app_settings)
    )
    config = runtime.app_settings
    app = FastAPI(
        title="Overture",
        version=APP_VERSION,
        description=(
            "Overture's own API, which its web interface uses. Sign in with the "
            "session cookie, or read with an API key; an API key never changes "
            "anything."
        ),
        license_info={"name": "AGPL-3.0-only", "identifier": "AGPL-3.0-only"},
        openapi_tags=[
            {"name": name, "description": description}
            for name, description in _TAGS.items()
        ],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
        generate_unique_id_function=_operation_id,
        max_body_size=MAX_REQUEST_BODY,
    )
    app.state.runtime = runtime
    app.openapi = partial(_openapi, app.openapi)
    app.middleware("http")(partial(security_middleware, app_config=config))
    # Registered second so request logging is outermost: it also records
    # requests rejected by CSRF validation and is the unhandled-error boundary.
    app.middleware("http")(partial(request_logging_middleware, app_config=config))
    _register_error_handlers(app)
    _register_api_routes(app)
    app.include_router(websocket_router)
    _mount_static_frontend(app, frontend_dir=frontend_dir)
    return app


def _error(
    body: ErrorResponse | ValidationErrorResponse,
    status: int,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialise an error body, which redacts its free text, as the response."""
    return JSONResponse(
        body.model_dump(mode="json"), status_code=status, headers=headers
    )


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Return a routing or framework error, with the headers it names.

    A 405 names the methods the path allows in ``Allow``, as RFC 9110 requires.
    """
    return _error(ErrorResponse(detail=str(exc.detail)), exc.status_code, exc.headers)


async def public_service_exception_handler(
    _request: Request, exc: PublicServiceError | MediaServerError
) -> JSONResponse:
    """Return a service-layer error."""
    return _error(ErrorResponse(detail=exc.message), exc.status_code)


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return where and why a request failed validation, never what it sent."""
    issues = [
        ValidationIssue(loc=list(error["loc"]), msg=error["msg"], type=error["type"])
        for error in exc.errors()
    ]
    return _error(ValidationErrorResponse(detail=issues), 422)


def _register_error_handlers(app: FastAPI) -> None:
    """Register sanitized exception handlers."""
    # Starlette types a handler as taking any Exception; each of these takes
    # only the type it is registered for, which Starlette guarantees.
    app.add_exception_handler(
        StarletteHTTPException,
        cast("Any", http_exception_handler),
    )
    app.add_exception_handler(
        PublicServiceError,
        cast("Any", public_service_exception_handler),
    )
    app.add_exception_handler(
        MediaServerError,
        cast("Any", public_service_exception_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast("Any", validation_exception_handler),
    )


def _register_api_routes(app: FastAPI) -> None:
    """Register the API routers under the API prefix."""
    for router in (
        art_router,
        asset_manager_router,
        auth_router,
        backup_router,
        bulk_assets_router,
        collections_router,
        collection_groups_router,
        docs_router,
        health_router,
        library_router,
        library_filters_router,
        job_snapshots_router,
        media_server_router,
        notifications_router,
        catalog_router,
        realtime_router,
        server_audit_router,
        settings_router,
        stats_router,
        sync_router,
        themes_router,
        tmdb_router,
    ):
        app.include_router(router, prefix=API_PREFIX)


@docs_router.get("/openapi.json", include_in_schema=False)
async def openapi_endpoint(request: Request) -> JSONResponse:
    """Return the OpenAPI schema for authenticated clients."""
    return JSONResponse(request.app.openapi())


@docs_router.get("/docs", include_in_schema=False)
async def swagger_ui_html(request: Request) -> HTMLResponse:
    """Swagger UI documentation page for authenticated clients."""
    response = get_swagger_ui_html(
        openapi_url=f"{API_PREFIX}/openapi.json",
        title=f"{request.app.title} - Swagger UI",
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "frame-ancestors 'none'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: blob: https://fastapi.tiangolo.com; "
        "connect-src 'self'"
    )
    return response


@health_router.get("/health")
async def health() -> HealthResponse:
    """Unauthenticated liveness probe."""
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        python=sys.version.split()[0],
    )


@health_router.get("/ready", responses={503: {"model": ReadinessResponse}})
async def ready(response: Response, runtime: RuntimeDep) -> ReadinessResponse:
    """Readiness probe for dependencies required to serve authenticated traffic."""
    checks = await runtime.readiness_checks()
    ready_status = all(checks.values())
    if not ready_status:
        response.status_code = 503
    return ReadinessResponse(
        status="ready" if ready_status else "not_ready",
        checks=checks,
    )


async def _authenticate_websocket(
    websocket: WebSocket, runtime: RuntimeServices
) -> tuple[SecretStr | None, str | None, float | None] | None:
    """Validate WebSocket session cookies.

    Returns (token, session_hash, timeout_seconds), or None if rejected.
    """
    if runtime.app_settings.AUTH_MODE == "none":
        return None, None, None

    cookie = websocket.cookies.get(SESSION_COOKIE)
    token = SecretStr(cookie) if cookie else None
    if token is None:
        logger.info("WebSocket rejected: not signed in")
        await websocket.close(code=4001, reason="Not authenticated")
        return None

    expires = await runtime.auth.token_expiry(token)
    if expires is None:
        logger.info("WebSocket rejected: session expired or revoked")
        await websocket.close(code=4001, reason="Invalid token")
        return None

    session_hash = runtime.auth.token_hash(token)
    timeout_seconds = max(0, (expires - utc_now()).total_seconds())
    return token, session_hash, timeout_seconds


@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, runtime: RuntimeDep) -> None:
    """Manage the authenticated WebSocket event stream."""
    if not websocket_origin_allowed(
        origin=websocket.headers.get("origin", ""),
        host=websocket.headers.get("host", ""),
        scheme=websocket.url.scheme,
        app_config=runtime.app_settings,
    ):
        logger.warning("WebSocket rejected: origin not allowed")
        await websocket.close(code=4003, reason="Invalid origin")
        return

    auth_info = await _authenticate_websocket(websocket, runtime)
    if auth_info is None:
        return

    token, session_hash, timeout_seconds = auth_info
    await runtime.websockets.connect(websocket, session_hash=session_hash)
    if token and await runtime.auth.token_expiry(token) is None:
        runtime.websockets.disconnect(websocket)
        return

    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                data = await websocket.receive_json()
                if data == {"event": "client.resync"}:
                    logger.debug("WebSocket client requested a state resync")
                    await send_client_resync(
                        websocket, runtime.websockets, runtime.realtime_snapshot()
                    )
                else:
                    logger.debug(
                        "Ignoring an unsupported WebSocket message (%s)",
                        type(data).__name__,
                    )

    except TimeoutError:
        await websocket.close(code=4001, reason="Session expired")
    except WebSocketDisconnect:
        pass
    except (RuntimeError, ValueError) as e:
        logger.warning("WebSocket client error: %s", e)
    finally:
        runtime.websockets.disconnect(websocket)


def _exclude_non_page_paths(request: Request) -> None:
    """Reject api, ws and missing build-asset paths before frontend fallback."""
    if is_backend_path(request.url.path) or request.url.path.startswith(
        f"{BUILD_ASSETS_PATH}/"
    ):
        raise StarletteHTTPException(status_code=404, detail="Not Found")


def _mount_static_frontend(app: FastAPI, frontend_dir: Path | None = None) -> None:
    """Serve the built frontend when present in the runtime image."""
    static_dir = frontend_dir if frontend_dir is not None else FRONTEND_DIR
    if static_dir.is_dir():
        assets_dir = static_dir / BUILD_ASSETS_PATH.strip("/")
        if assets_dir.is_dir():
            # A file a build lacks is not found, never answered with the page,
            # which a browser cannot load as the script or style it asked for.
            app.mount(
                BUILD_ASSETS_PATH,
                StaticFiles(directory=assets_dir),
                name="assets",
            )
        frontend_router = APIRouter(dependencies=[Depends(_exclude_non_page_paths)])
        frontend_router.frontend("/", directory=static_dir, fallback="index.html")
        app.include_router(frontend_router)
