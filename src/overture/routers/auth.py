"""Mutually exclusive password and OIDC login with local session cookies."""

lazy import logging
lazy from collections.abc import Sequence
lazy from enum import Enum
lazy from typing import Annotated, Any

lazy from fastapi import APIRouter, Depends, Query, Request, Response, params
lazy from fastapi.routing import APIRoute
lazy from pydantic import SecretStr
lazy from starlette.responses import RedirectResponse

lazy from ..dependencies import AuthDep, WebSocketsDep, require_media_server
lazy from ..schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    AuthConfig,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
)
lazy from ..schemas.common import StatusResponse
lazy from ..services.auth import AuthService, LoginSession
lazy from ..services.oidc import (
    TRANSACTION_COOKIE,
    TRANSACTION_COOKIE_PATH,
    TRANSACTION_SECONDS,
    OIDCError,
)
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.http_security import CSRF_COOKIE, SESSION_COOKIE, SIGNED_OUT_PATH
lazy from ..ws.connection_manager import ConnectionManager
lazy from .parameters import (
    ApiKeyHeader,
    ApiKeyIdPath,
    AuthTokenCookie,
    ForwardedForHeader,
)
lazy from .responses import (
    AUTH_RESPONSES,
    MEDIA_SERVER_RESPONSES,
    OIDC_OFF,
    TOO_MANY_ATTEMPTS,
    Responses,
    errors,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


#: ``openapi_extra`` of a POST that only reads, which an API key may call.
READS_ONLY: dict[str, Any] = {"x-reads-only": True}
_READ_METHODS = frozenset({"GET", "HEAD"})


async def require_auth(
    request: Request,
    auth: AuthDep,
    token: AuthTokenCookie = None,
    api_key: ApiKeyHeader = None,
) -> None:
    """Require a live session, or an API key for a request that only reads.

    Raises:
        PublicServiceError: 401 without valid credentials, 403 when an API key
            asks for a change.
    """
    if api_key is None:
        await auth.require_token(SecretStr(token) if token else None)
        return
    await auth.require_api_key(SecretStr(api_key))
    route = request.scope.get("route")
    if request.method not in _READ_METHODS and not (
        isinstance(route, APIRoute) and route.openapi_extra == READS_ONLY
    ):
        raise PublicServiceError(403, "API keys can only read")


def authenticated_router(
    *,
    prefix: str = "",
    tags: list[str | Enum] | None = None,
    dependencies: Sequence[params.Depends] = (),
    responses: Responses | None = None,
) -> APIRouter:
    """A router whose every route needs signing in, as its schema says.

    *dependencies* and *responses* are what its routes need besides.
    """
    return APIRouter(
        prefix=prefix,
        tags=tags,
        dependencies=[Depends(require_auth), *dependencies],
        responses={**AUTH_RESPONSES, **(responses or {})},
    )


def media_server_router(*, prefix: str, tags: list[str | Enum]) -> APIRouter:
    """An authenticated router whose routes all need a media server."""
    return authenticated_router(
        prefix=prefix,
        tags=tags,
        dependencies=[Depends(require_media_server)],
        responses=MEDIA_SERVER_RESPONSES,
    )


@router.post(
    "/login",
    responses={
        **errors({401: "The password is wrong", 404: "Password login is disabled"}),
        **TOO_MANY_ATTEMPTS,
    },
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthDep,
    websockets: WebSocketsDep,
    x_forwarded_for: ForwardedForHeader = None,
) -> LoginResponse:
    """Authenticate and issue opaque session and CSRF cookies."""
    session = await auth.login(
        body,
        socket_ip=request.client.host if request.client else "unknown",
        x_forwarded_for=x_forwarded_for or "",
    )

    await _revoke_session(request, auth, websockets)
    _set_session(response, session)
    return session.response


def _set_session(response: Response, session: LoginSession) -> None:
    """Keep password and OIDC cookie attributes identical."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.token.get_secret_value(),
        httponly=True,
        secure=session.secure,
        samesite="strict",
        max_age=session.max_age,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=session.csrf_token.get_secret_value(),
        httponly=False,
        secure=session.secure,
        samesite="strict",
        max_age=session.max_age,
        path="/",
    )


def _clear_transaction(response: Response, auth: AuthService) -> None:
    secure, _ = auth.cookie_security()
    response.delete_cookie(
        TRANSACTION_COOKIE,
        path=TRANSACTION_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def _oidc_failure(error: OIDCError, auth: AuthService) -> RedirectResponse:
    logger.warning("OIDC sign-in failed: %s", error.code)
    response = RedirectResponse(
        f"{SIGNED_OUT_PATH}&auth_error=oidc_{error.code}", status_code=303
    )
    _clear_transaction(response, auth)
    return response


@router.get("/oidc/login", responses={**OIDC_OFF, **TOO_MANY_ATTEMPTS})
async def oidc_login(
    request: Request,
    auth: AuthDep,
    return_to: Annotated[str, Query(max_length=2048)] = "/",
    x_forwarded_for: ForwardedForHeader = None,
) -> RedirectResponse:
    """Start a browser-bound authorization code flow with the trusted provider."""
    if auth.oidc is None:
        raise PublicServiceError(404, "OIDC login is disabled")
    auth.check_oidc_rate(
        request.client.host if request.client else "unknown", x_forwarded_for or ""
    )
    try:
        url, binding = await auth.oidc.start(
            return_to, request.cookies.get(TRANSACTION_COOKIE)
        )
    except OIDCError as exc:
        return _oidc_failure(exc, auth)
    response = RedirectResponse(url, status_code=302)
    secure, _ = auth.cookie_security()
    response.set_cookie(
        TRANSACTION_COOKIE,
        binding,
        path=TRANSACTION_COOKIE_PATH,
        max_age=TRANSACTION_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    return response


@router.get("/oidc/callback", responses=OIDC_OFF)
async def oidc_callback(
    request: Request, auth: AuthDep, websockets: WebSocketsDep
) -> RedirectResponse:
    """Validate a single-use authorization response and establish local cookies."""
    if auth.oidc is None:
        raise PublicServiceError(404, "OIDC login is disabled")
    binding = request.cookies.get(TRANSACTION_COOKIE)
    try:
        if any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            auth.oidc.discard(binding)
            raise OIDCError("invalid")
        identity = await auth.oidc.complete(request.query_params, binding)
    except OIDCError as exc:
        return _oidc_failure(exc, auth)
    response = RedirectResponse(identity.return_to, status_code=303)
    await _revoke_session(request, auth, websockets)
    _set_session(response, await auth.new_session(id_token=identity.id_token))
    _clear_transaction(response, auth)
    return response


@router.post("/logout")
async def logout(
    request: Request, response: Response, auth: AuthDep, websockets: WebSocketsDep
) -> LogoutResponse:
    """Revoke locally before offering provider logout."""
    id_token = await _revoke_session(request, auth, websockets)
    secure, _max_age = auth.cookie_security()
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=secure,
        samesite="strict",
    )
    response.delete_cookie(
        key=CSRF_COOKIE,
        path="/",
        httponly=False,
        secure=secure,
        samesite="strict",
    )
    if auth.oidc is None:
        return LogoutResponse(status="ok", redirect_url=SIGNED_OUT_PATH)
    auth.oidc.discard(request.cookies.get(TRANSACTION_COOKIE))
    _clear_transaction(response, auth)
    redirect_url = await auth.oidc.logout_url(id_token) if id_token else SIGNED_OUT_PATH
    return LogoutResponse(status="ok", redirect_url=redirect_url)


async def _revoke_session(
    request: Request, auth: AuthService, websockets: ConnectionManager
) -> str | None:
    """Revoke database access and disconnect existing event streams together."""
    cookie = request.cookies.get(SESSION_COOKIE)
    token = SecretStr(cookie) if cookie else None
    id_token = await auth.revoke(token)
    if token is not None:
        websockets.revoke_session(auth.token_hash(token))
    return id_token


# Anyone may ask, signed in or not, which an empty requirement beside the
# session's says.
@router.get("/me", openapi_extra={"security": [{}, {"Session": []}]})
async def me(auth: AuthDep, token: AuthTokenCookie = None) -> MeResponse:
    """Check auth status."""
    return await auth.me_response(SecretStr(token) if token else None)


@router.get("/config")
async def auth_config(auth: AuthDep) -> AuthConfig:
    """Public login configuration."""
    return auth.public_config()


#: The read-only keys scripts sign in with.
api_keys_router = authenticated_router(prefix="/api-keys")


@api_keys_router.get("")
async def list_api_keys(auth: AuthDep) -> list[ApiKeyRead]:
    """List the API keys, without the keys themselves."""
    return await auth.api_keys()


@api_keys_router.post(
    "",
    responses=errors({409: "A key has that name already"}),
)
async def create_api_key(body: ApiKeyCreate, auth: AuthDep) -> ApiKeyCreated:
    """Create a read-only API key and return it, this once."""
    return await auth.create_api_key(body.name)


@api_keys_router.delete(
    "/{key_id}",
    responses=errors({404: "No key has that ID"}),
)
async def delete_api_key(key_id: ApiKeyIdPath, auth: AuthDep) -> StatusResponse:
    """Revoke an API key."""
    return await auth.delete_api_key(key_id)


router.include_router(api_keys_router)
