"""Local-only Playwright fixture; never used by the production entry point."""

lazy from collections.abc import AsyncGenerator
lazy from contextlib import asynccontextmanager
lazy from pathlib import Path
lazy from typing import Annotated, Literal, override

lazy import httpx2
lazy from fastapi import FastAPI, Query, Request
lazy from pydantic import AnyHttpUrl, SecretStr
lazy from sqlalchemy.ext.asyncio import create_async_engine
lazy from starlette.responses import Response

lazy from overture.config import Settings
lazy from overture.db import metadata
lazy from overture.db.session import Database
lazy from overture.domain import ServerType
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


def create_browser_app() -> FastAPI:
    """Build production auth routes and assets plus a cross-site test IdP."""
    config = Settings(
        AUTH_MODE="oidc",
        APP_URL="http://127.0.0.1:8697",
        OIDC_ISSUER_URL=AnyHttpUrl("http://localhost:8697/provider"),
        OIDC_CLIENT_ID="overture",
        OIDC_CLIENT_SECRET=SecretStr("test-client-secret"),
        MEDIA_SERVER=ServerType.PLEX,
        MEDIA_SERVER_URL="http://127.0.0.1:32400",
        MEDIA_SERVER_API_KEY=SecretStr("test-media-key"),
    )
    database = Database(
        "sqlite+aiosqlite://", engine=create_async_engine("sqlite+aiosqlite://")
    )
    runtime = build_runtime(
        app_settings=config,
        database=database,
        config_dir=Path(__file__).resolve().parents[1] / ".pytest-run-tmp" / "oidc",
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        try:
            yield
        finally:
            await runtime.stop()

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
