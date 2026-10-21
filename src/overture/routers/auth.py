"""Mutually exclusive password and OIDC login with local session cookies."""

lazy import logging
lazy from typing import Annotated

lazy from fastapi import APIRouter, Query, Request, Response
lazy from starlette.responses import RedirectResponse

lazy from ..dependencies import AuthDep, RuntimeDep
lazy from ..runtime import RuntimeServices
lazy from ..schemas.auth import (
    AuthConfig,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
)
lazy from ..services.auth import AuthService, LoginSession
lazy from ..services.oidc import (
    TRANSACTION_COOKIE,
    TRANSACTION_COOKIE_PATH,
    TRANSACTION_SECONDS,
    OIDCError,
)
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.http_security import CSRF_COOKIE, SESSION_COOKIE, SIGNED_OUT_PATH
lazy from .parameters import AuthTokenCookie, ForwardedForHeader

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


async def require_auth(auth: AuthDep, token: AuthTokenCookie = None) -> None:
    """Require a live application session."""
    await auth.require_token(token)


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthDep,
    runtime: RuntimeDep,
    x_forwarded_for: ForwardedForHeader = None,
) -> LoginResponse:
    """Authenticate and issue opaque session and CSRF cookies."""
    session = await auth.login(
        body,
        socket_ip=request.client.host if request.client else "unknown",
        x_forwarded_for=x_forwarded_for or "",
    )

    await _revoke_session(request, auth, runtime)
    _set_session(response, session)
    return session.response


def _set_session(response: Response, session: LoginSession) -> None:
    """Keep password and OIDC cookie attributes identical."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.token,
        httponly=True,
        secure=session.secure,
        samesite="strict",
        max_age=session.max_age,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=session.csrf_token,
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


@router.get("/oidc/login")
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


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request, auth: AuthDep, runtime: RuntimeDep
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
    await _revoke_session(request, auth, runtime)
    _set_session(response, await auth.new_session(id_token=identity.id_token))
    _clear_transaction(response, auth)
    return response


@router.post("/logout")
async def logout(
    request: Request, response: Response, auth: AuthDep, runtime: RuntimeDep
) -> LogoutResponse:
    """Revoke locally before offering provider logout."""
    id_token = await _revoke_session(request, auth, runtime)
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
    request: Request, auth: AuthService, runtime: RuntimeServices
) -> str | None:
    """Revoke database access and disconnect existing event streams together."""
    token = request.cookies.get(SESSION_COOKIE)
    id_token = await auth.revoke(token)
    if token:
        runtime.websockets.revoke_session(auth.token_hash(token))
    return id_token


@router.get("/me")
async def me(auth: AuthDep, token: AuthTokenCookie = None) -> MeResponse:
    """Check auth status."""
    return await auth.me_response(token)


@router.get("/config")
async def auth_config(auth: AuthDep) -> AuthConfig:
    """Public login configuration."""
    return auth.public_config()
