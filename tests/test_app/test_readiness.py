"""Application readiness probe behavior."""

lazy from pathlib import Path
lazy from typing import cast

lazy from starlette.responses import Response

lazy from overture import main
lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.runtime import RuntimeServices
lazy from overture.schemas.app import ReadinessResponse
lazy from overture.services.art.phash import PhashService
lazy from tests.runtime_helpers import NoopAssets, make_runtime


class FakeRuntime:
    def __init__(self, checks: dict[str, bool]) -> None:
        self.checks = checks

    async def readiness_checks(self) -> dict[str, bool]:
        return self.checks


async def test_ready_returns_200_when_all_checks_pass() -> None:
    response = Response()

    body = await main.ready(
        response,
        runtime=cast(
            "RuntimeServices",
            FakeRuntime(
                {
                    "config": True,
                    "database": True,
                    "downloads": True,
                    "collection_theme_manager": True,
                    "scheduler": True,
                    "websocket_ping": True,
                }
            ),
        ),
    )

    assert response.status_code == 200
    assert body == ReadinessResponse(
        status="ready",
        checks={
            "config": True,
            "database": True,
            "downloads": True,
            "collection_theme_manager": True,
            "scheduler": True,
            "websocket_ping": True,
        },
    )


async def test_ready_returns_503_when_database_check_fails() -> None:
    response = Response()

    body = await main.ready(
        response,
        runtime=cast(
            "RuntimeServices",
            FakeRuntime(
                {
                    "config": True,
                    "database": False,
                    "downloads": True,
                    "collection_theme_manager": True,
                    "scheduler": True,
                    "websocket_ping": True,
                }
            ),
        ),
    )

    assert response.status_code == 503
    assert body.status == "not_ready"
    assert body.checks["database"] is False


async def test_readiness_reports_exactly_the_runtime_capabilities(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    """The probe's keys must track the runtime, not a list that drifts from it."""
    runtime = make_runtime(
        config_dir=tmp_path,
        app_config=app_config,
        database=database,
        assets=NoopAssets(app_config=app_config),
    )

    runtime.phash = PhashService(app_config=app_config)
    checks = await runtime.readiness_checks()

    assert set(checks) == {
        "config",
        "database",
        "theme_runtime",
        "phash",
        "asset_schedules",
        "sync_schedules",
        "downloads",
        "scheduler",
        "websocket_ping",
    }
