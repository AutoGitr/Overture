"""Local-only Playwright fixture; never used by the production entry point."""

lazy import socket
lazy from collections.abc import AsyncGenerator
lazy from contextlib import asynccontextmanager
lazy from pathlib import Path
lazy from tempfile import TemporaryDirectory
lazy from typing import Annotated, Any, Literal, override

lazy import httpx2
lazy from fastapi import FastAPI, Query, Request
lazy from pydantic import AnyHttpUrl, SecretStr
lazy from starlette.responses import Response

lazy from overture.config import Settings
lazy from overture.db import metadata
lazy from overture.db.session import Database
lazy from overture.main import create_app
lazy from overture.runtime import build_runtime
lazy from overture.services.auth import AuthService
lazy from tests.oidc_provider import TestOIDCProvider


class BrowserAuth(AuthService):
    """Short-lived cookies exercise actual WebSocket expiry without clock mocks."""

    short_session = False

    @override
    def session_seconds(self) -> int:
        return 5 if self.short_session else super().session_seconds()


def _resolve_loopback_only(host: str, *args: Any, **kwargs: Any) -> Any:
    """Resolve only this machine, so a request off it fails instead of leaving."""
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise socket.gaierror(socket.EAI_NONAME, f"{host} is outside the test")
    return _getaddrinfo(host, *args, **kwargs)


_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = _resolve_loopback_only


def create_browser_app() -> FastAPI:
    """Build production auth routes and assets plus a cross-site test IdP."""
    config = Settings.model_validate(
        {
            "AUTH_MODE": "oidc",
            "APP_URL": "http://127.0.0.1:8697",
            "OIDC_ISSUER_URL": AnyHttpUrl("http://localhost:8697/provider"),
            "OIDC_CLIENT_ID": "overture",
            "OIDC_CLIENT_SECRET": SecretStr("test-client-secret"),
            # Sign-in needs no media server, and a configured one is looked up
            # on plex.tv; with none, nothing is reached beyond this process.
            "MEDIA_SERVER": "none",
        }
    )
    # Browser requests overlap. An in-memory StaticPool shares one transaction
    # across readers and writers, letting a read rollback undo session revocation.
    directory = TemporaryDirectory(prefix="overture-oidc-")
    database = Database(
        f"sqlite+aiosqlite:///{Path(directory.name).as_posix()}/test.db"
    )
    runtime = build_runtime(
        app_settings=config,
        database=database,
        config_dir=Path(directory.name),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        try:
            yield
        finally:
            await runtime.stop()
            directory.cleanup()

    app = FastAPI(lifespan=lifespan)
    provider = TestOIDCProvider(str(config.OIDC_ISSUER_URL))
    provider_app = FastAPI()

    async def respond(request: Request) -> Response:
        upstream = provider.handle(
            httpx2.Request(
                request.method,
                str(request.url),
                headers=dict(request.headers),
                content=await request.body(),
            )
        )
        return Response(upstream.content, upstream.status_code, dict(upstream.headers))

    provider_app.add_api_route("/{path:path}", respond, methods=["GET", "POST"])
    app.mount("/provider", provider_app)

    @app.get("/__test/reset")
    async def reset(
        auto_login: bool = False,
        scenario: Annotated[
            Literal["success", "denied", "expiry", "local_logout"], Query()
        ] = "success",
    ) -> dict[str, bool]:
        runtime.auth.close()
        config.OIDC_AUTO_LOGIN = auto_login
        auth = BrowserAuth(config, database)
        auth.short_session = scenario == "expiry"
        runtime.auth = auth
        provider.claim_overrides = (
            {"aud": "another-client"} if scenario == "denied" else {}
        )
        provider.metadata_overrides = (
            {"end_session_endpoint": None} if scenario == "local_logout" else {}
        )
        provider.codes.clear()
        return {"ready": True}

    app.mount("/", create_app(runtime))
    return app


app = create_browser_app()
