"""Overture - Application entry point."""

lazy import asyncio
lazy import logging
lazy import sys
lazy from collections.abc import AsyncGenerator
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
lazy from fastapi.encoders import jsonable_encoder
lazy from fastapi.exceptions import RequestValidationError
lazy from fastapi.openapi.docs import get_swagger_ui_html
lazy from fastapi.routing import APIRoute
lazy from starlette.exceptions import HTTPException as StarletteHTTPException
lazy from starlette.responses import HTMLResponse, JSONResponse

lazy from .config import API_PREFIX, Settings
lazy from .dependencies import RuntimeDep
lazy from .media_servers.errors import MediaServerError
lazy from .routers.art import router as art_router
lazy from .routers.asset_manager import router as asset_manager_router
lazy from .routers.auth import require_auth
lazy from .routers.auth import router as auth_router
lazy from .routers.backup import router as backup_router
lazy from .routers.bulk_assets import router as bulk_assets_router
lazy from .routers.collections import router as collections_router
lazy from .routers.job_snapshots import router as job_snapshots_router
lazy from .routers.library import router as library_router
lazy from .routers.media_server import router as media_server_router
lazy from .routers.public_dataset import router as public_dataset_router
lazy from .routers.realtime import router as realtime_router
lazy from .routers.server_audit import router as server_audit_router
lazy from .routers.settings import router as settings_router
lazy from .routers.stats import router as stats_router
lazy from .routers.sync import router as sync_router
lazy from .routers.themes import router as themes_router
lazy from .routers.tmdb import router as tmdb_router
lazy from .runtime import RuntimeServices, build_runtime
lazy from .runtime_paths import FRONTEND_DIR
lazy from .schemas.app import HealthResponse, ReadinessResponse
lazy from .utils.errors import PublicServiceError
lazy from .utils.http_security import (
    SESSION_COOKIE,
    security_middleware,
    websocket_origin_allowed,
)
lazy from .utils.request_logging import request_logging_middleware
lazy from .utils.security import (
    REDACTED,
    is_sensitive_field,
    sanitise_for_output,
)
lazy from .utils.time import utc_now
lazy from .version import APP_VERSION
lazy from .ws.resync import send_client_resync

logger = logging.getLogger(__name__)

docs_router = APIRouter(dependencies=[Depends(require_auth)])
health_router = APIRouter(tags=["health"])
websocket_router = APIRouter()


def _operation_id(route: APIRoute) -> str:
    """Return stable semantic OpenAPI operation IDs."""
    return route.name


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Start and stop the configured runtime services."""
    runtime: RuntimeServices = app.state.runtime
    try:
        await runtime.start(app_version=APP_VERSION)
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
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.state.runtime = runtime
    app.middleware("http")(partial(security_middleware, app_config=config))
    # Registered second so request logging is outermost: it also records
    # requests rejected by CSRF validation and is the unhandled-error boundary.
    app.middleware("http")(partial(request_logging_middleware, app_config=config))
    _register_error_handlers(app)
    _register_api_routes(app)
    app.include_router(websocket_router)
    _mount_static_frontend(app, frontend_dir=frontend_dir)
    return app


def _sanitise_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Redact validation input values when their location names a secret field."""
    safe_errors: list[dict[str, Any]] = []
    for error in errors:
        safe_error = sanitise_for_output(error)
        loc = error.get("loc", ())
        if any(is_sensitive_field(part) for part in loc):
            safe_error["input"] = REDACTED
        safe_errors.append(safe_error)
    return safe_errors


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Ensure application HTTP errors cannot return raw credentials."""
    return JSONResponse(
        {
            "detail": request.app.state.runtime.redactor.output(
                jsonable_encoder(exc.detail)
            )
        },
        status_code=exc.status_code,
        headers=sanitise_for_output(exc.headers) if exc.headers else None,
    )


async def public_service_exception_handler(
    request: Request, exc: PublicServiceError | MediaServerError
) -> JSONResponse:
    """Return service-layer public errors through one sanitized boundary."""
    return JSONResponse(
        {"detail": request.app.state.runtime.redactor.output(exc.message)},
        status_code=exc.status_code,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation errors with body/header/cookie secrets redacted."""
    return JSONResponse(
        {
            "detail": request.app.state.runtime.redactor.output(
                _sanitise_validation_errors(jsonable_encoder(exc.errors()))
            )
        },
        status_code=422,
    )


def _register_error_handlers(app: FastAPI) -> None:
    """Register sanitized exception handlers."""
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
        docs_router,
        health_router,
        library_router,
        job_snapshots_router,
        media_server_router,
        public_dataset_router,
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
) -> tuple[str | None, str | None, float | None] | None:
    """Validate WebSocket session cookies.

    Returns (token, session_hash, timeout_seconds), or None if rejected.
    """
    if runtime.app_settings.AUTH_MODE == "none":
        return None, None, None

    token = websocket.cookies.get(SESSION_COOKIE)
    if not token:
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
                    await send_client_resync(websocket, runtime)
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


def _exclude_api_and_ws(request: Request) -> None:
    """Reject requests targeting api or ws namespaces before frontend fallback."""
    first_segment = request.url.path.strip("/").split("/", 1)[0].lower()
    if first_segment in {API_PREFIX.strip("/"), "ws"}:
        raise StarletteHTTPException(status_code=404, detail="Not Found")


def _mount_static_frontend(app: FastAPI, frontend_dir: Path | None = None) -> None:
    """Serve the built frontend when present in the runtime image."""
    static_dir = frontend_dir if frontend_dir is not None else FRONTEND_DIR
    if static_dir.is_dir():
        frontend_router = APIRouter(dependencies=[Depends(_exclude_api_and_ws)])
        frontend_router.frontend("/", directory=static_dir, fallback="index.html")
        app.include_router(frontend_router)
