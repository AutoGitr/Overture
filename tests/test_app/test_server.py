"""The server entry point configures logging once, then serves the app."""

lazy from pathlib import Path
lazy from typing import Any

lazy import pytest

lazy import overture.cli as server
lazy from overture.config import HOST, PORT, Settings
lazy from overture.db.session import Database
lazy from overture.runtime import build_runtime
lazy from overture.utils.security import Redactor


def test_logging_is_configured_from_the_runtime_before_uvicorn_starts(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
    tmp_path: Path,
) -> None:
    runtime = build_runtime(
        app_settings=app_config, database=database, config_dir=tmp_path
    )
    calls: list[tuple[str, Any]] = []

    def configure_logging(config: Settings, redactor: Redactor) -> None:
        calls.append(("logging", (config, redactor)))

    def run(app: Any, **options: Any) -> None:
        calls.append(("serve", (app, options)))

    def build(**kwargs: Any) -> Any:
        return runtime

    monkeypatch.setattr(server, "build_runtime", build)
    monkeypatch.setattr(server, "configure_logging", configure_logging)
    monkeypatch.setattr(server.uvicorn, "run", run)

    server.serve(app_config)

    assert [name for name, _ in calls] == ["logging", "serve"]
    assert calls[0][1] == (runtime.app_settings, runtime.redactor)
    app, options = calls[1][1]
    assert app.state.runtime is runtime
    assert options == {
        "host": HOST,
        "port": PORT,
        "proxy_headers": False,
        "timeout_graceful_shutdown": 20,
        "log_config": None,
        "access_log": False,
    }
