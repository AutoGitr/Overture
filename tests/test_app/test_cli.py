"""The overture command checks, configures and hashes without starting the runtime."""

lazy import http.client
lazy import io
lazy import os
lazy import subprocess
lazy from collections.abc import Iterator
lazy from importlib.machinery import ModuleSpec
lazy from ipaddress import ip_address
lazy from pathlib import Path
lazy from unittest.mock import Mock

lazy import pytest
lazy from alembic.config import Config

lazy from overture import cli
lazy from overture.config import (
    RuntimeSettings,
    Settings,
    load_configuration,
    read_configuration,
    write_configuration,
)
lazy from overture.db.session import Database
lazy from overture.passwords import hash_password, validate_hash, verify_password
lazy from overture.services.themes.youtube_resolver import THEME_TOOLS
lazy from tests.runtime_helpers import make_runtime


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OVERTURE_CONFIG_FILE", raising=False)


def test_password_hash_ignores_configuration_and_only_prints_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    password = "short!"

    def answer(_: str) -> str:
        return password

    monkeypatch.setattr(cli, "prompt_secret", answer)
    path = tmp_path / "overture.env"
    original = "malformed configuration '"
    path.write_text(original)
    monkeypatch.setenv("OVERTURE_CONFIG_FILE", str(path))
    monkeypatch.setenv("OVERTURE_PORT", "invalid")
    monkeypatch.setenv("APP_PASSWORD_HASH", "obsolete hash")
    monkeypatch.chdir(tmp_path)

    def fail_check(settings: Settings) -> None:
        pytest.fail("Hash generation must not check application prerequisites")

    monkeypatch.setattr(cli, "check", fail_check)
    cli.main(["password", "hash"])
    assert list(tmp_path.iterdir()) == [path]
    assert path.read_text() == original
    output = capsys.readouterr().out
    assert output.startswith("APP_PASSWORD_HASH='$argon2id$")
    assert output.endswith("'\n")
    assert len(output.splitlines()) == 1
    assert password not in output
    encoded = output.removeprefix("APP_PASSWORD_HASH='").removesuffix("'\n")
    assert validate_hash(encoded) == encoded
    assert verify_password(password.encode(), encoded.encode())


def test_mismatch_and_cancellation_do_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers: Iterator[str] = iter(["a long simple password", "a different password"])

    def answer(_: str) -> str:
        return next(answers)

    monkeypatch.setattr(cli, "prompt_secret", answer)
    path = tmp_path / "overture.env"
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="do not match"):
        cli.main(["password", "hash"])
    assert not capsys.readouterr().out
    assert not list(tmp_path.iterdir())

    def cancel(_: str) -> str:
        raise EOFError

    monkeypatch.setattr(cli, "prompt_secret", cancel)
    monkeypatch.setattr("builtins.input", cancel)
    with pytest.raises(SystemExit, match="Cancelled"):
        cli.main(["password", "hash"])
    assert not capsys.readouterr().out
    with pytest.raises(SystemExit, match="Cancelled"):
        cli.main(["setup", "--config-file", str(path)])
    assert not path.exists()


@pytest.mark.parametrize("password", ["", "x" * 1025, "\u00e9" * 513])
def test_password_hash_invalid_input_produces_no_hash(
    password: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def answer(_: str) -> str:
        return password

    monkeypatch.setattr(cli, "prompt_secret", answer)
    with pytest.raises(SystemExit, match=r"empty|UTF-8 bytes"):
        cli.main(["password", "hash"])
    assert not capsys.readouterr().out


def test_password_hash_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("piped-password-test\n"))
    cli.main(["password", "hash", "--password-stdin"])
    output = capsys.readouterr().out
    assert output.startswith("APP_PASSWORD_HASH='$argon2id$")
    assert "piped-password-test" not in output
    encoded = output.removeprefix("APP_PASSWORD_HASH='").removesuffix("'\n")
    assert validate_hash(encoded) == encoded
    assert verify_password(b"piped-password-test", encoded.encode())


@pytest.mark.parametrize("stdin_content", ["\n", "\r\n", ""])
def test_password_hash_stdin_empty_rejected(
    stdin_content: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_content))
    with pytest.raises(SystemExit, match="empty"):
        cli.main(["password", "hash", "--password-stdin"])
    assert not capsys.readouterr().out


def test_check_does_not_start_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEDIA_SERVER", "plex")
    monkeypatch.setenv("MEDIA_SERVER_URL", "http://127.0.0.1:32400")
    monkeypatch.setenv("MEDIA_SERVER_API_KEY", "test-key")
    monkeypatch.setenv("APP_PASSWORD_HASH", hash_password("a long simple password"))
    called: list[Path] = []

    def record(settings: Settings) -> None:
        called.append(settings.OVERTURE_CONFIG_DIR)

    monkeypatch.setattr(cli, "check", record)

    def fail_build(**kwargs: object) -> None:
        pytest.fail("check must not construct a runtime")

    monkeypatch.setattr(cli, "build_runtime", fail_build)
    monkeypatch.setenv("OVERTURE_CONFIG_DIR", str(tmp_path))
    cli.main(["check"])
    assert called == [tmp_path]


@pytest.mark.parametrize("password", ["short", "a long simple password"])
def test_setup_saves_validated_configuration(
    password: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(["plex", "http://127.0.0.1:32400", "password", "", ""])
    secret_answers = iter(["private-api-key", password, password])

    def answer(_: str) -> str:
        return next(answers)

    def secret_answer(_: str) -> str:
        return next(secret_answers)

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(cli, "prompt_secret", secret_answer)
    path = tmp_path / "configuration" / "overture.env"
    cli.main(["setup", "--config-file", str(path)])
    settings = load_configuration(Settings, path)
    assert settings.MEDIA_SERVER_API_KEY.get_secret_value() == "private-api-key"
    assert verify_password(
        password.encode(),
        settings.APP_PASSWORD_HASH.get_secret_value().encode(),
    )
    output = capsys.readouterr().out
    assert "private-api-key" not in output
    assert password not in output
    if os.name == "posix":
        assert path.parent.stat().st_mode & 0o777 == 0o750


def test_missing_frontend_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def checked(_: Path) -> None:
        pass

    def checked_tools() -> None:
        pass

    monkeypatch.setattr(cli, "verify_config_dir", checked)
    monkeypatch.setattr(cli, "verify_theme_tools", checked_tools)
    monkeypatch.setattr(cli, "FRONTEND_DIR", tmp_path)
    with pytest.raises(ValueError, match="frontend is missing"):
        cli.check(app_config)


def test_missing_migrations_are_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def checked(_: Path) -> None:
        pass

    def checked_tools() -> None:
        pass

    def missing_migrations() -> Config:
        config = Config()
        config.set_main_option("script_location", str(tmp_path / "missing"))
        return config

    (tmp_path / "index.html").touch()
    monkeypatch.setattr(cli, "verify_config_dir", checked)
    monkeypatch.setattr(cli, "verify_theme_tools", checked_tools)
    monkeypatch.setattr(cli, "FRONTEND_DIR", tmp_path)
    monkeypatch.setattr(cli, "alembic_config", missing_migrations)
    with pytest.raises(ValueError, match="migrations are damaged"):
        cli.check(app_config)


def test_version_does_not_validate_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OVERTURE_PORT", "invalid-private-value")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == cli.APP_VERSION


def test_setup_rerun_keeps_saved_secrets_on_empty_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "overture.env"
    encoded = hash_password("a long simple password")
    write_configuration(
        path,
        {
            "MEDIA_SERVER": "plex",
            "MEDIA_SERVER_URL": "http://127.0.0.1:32400",
            "MEDIA_SERVER_API_KEY": "saved-api-key",
            "APP_PASSWORD_HASH": encoded,
        },
    )

    def accept_default(_: str) -> str:
        return ""

    monkeypatch.setattr("builtins.input", accept_default)
    monkeypatch.setattr(cli, "prompt_secret", accept_default)
    cli.main(["setup", "--config-file", str(path)])
    saved = read_configuration(path)
    assert saved["MEDIA_SERVER_API_KEY"] == "saved-api-key"
    assert saved["APP_PASSWORD_HASH"] == encoded


def test_config_dir_must_exist_and_be_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli.verify_config_dir(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        cli.verify_config_dir(tmp_path / "missing")

    def read_only(_path: object, mode: int) -> bool:
        return not mode & os.W_OK

    monkeypatch.setattr(os, "access", read_only)
    with pytest.raises(ValueError, match="is not writable"):
        cli.verify_config_dir(tmp_path)


def test_serve_exits_immediately_when_config_is_not_writable(
    app_config: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_config.OVERTURE_CONFIG_DIR = tmp_path
    build = Mock()
    monkeypatch.setattr(cli, "load_configuration", Mock(return_value=app_config))
    monkeypatch.setattr(cli, "build_runtime", build)
    monkeypatch.setattr(cli.os, "access", Mock(return_value=False))
    with pytest.raises(SystemExit, match="is not writable") as exc:
        cli.main(["serve"])
    assert exc.value.code != 0
    build.assert_not_called()


@pytest.mark.parametrize(
    ("missing_tool", "failing_tool", "missing_package", "message"),
    [
        (None, None, None, None),
        ("deno", None, None, "deno is not installed"),
        (None, "ffmpeg", None, "ffmpeg failed execution check"),
        (None, None, "yt_dlp_ejs", "yt_dlp_ejs package is missing"),
    ],
)
def test_theme_tools_are_checked(
    monkeypatch: pytest.MonkeyPatch,
    missing_tool: str | None,
    failing_tool: str | None,
    missing_package: str | None,
    message: str | None,
) -> None:
    executed: list[list[str]] = []

    def which(tool: str) -> str | None:
        return None if tool == missing_tool else f"/usr/bin/{tool}"

    def run(args: list[str], **_kwargs: object) -> None:
        executed.append(args)
        if args[0] == failing_tool:
            raise subprocess.CalledProcessError(1, args)

    def find_spec(name: str) -> ModuleSpec | None:
        return None if name == missing_package else ModuleSpec(name, loader=None)

    monkeypatch.setattr(cli.shutil, "which", which)
    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli.importlib.util, "find_spec", find_spec)
    if message is None:
        cli.verify_theme_tools()
        assert executed == [[tool, flag] for tool, flag in THEME_TOOLS.items()]
    else:
        with pytest.raises(ValueError, match=message):
            cli.verify_theme_tools()


def test_probe_waits_for_liveness_then_reports_readiness(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    statuses = iter([None, 503, 200, 503])
    requested: list[tuple[str, str]] = []

    def status(host: str, _port: int, path: str) -> int | None:
        requested.append((host, path))
        return next(statuses)

    def no_wait(_: float) -> None:
        pass

    monkeypatch.setattr(cli, "_status", status)
    monkeypatch.setattr(cli.time, "sleep", no_wait)
    cli.probe(RuntimeSettings.model_validate({"OVERTURE_HOST": "::"}))
    assert requested == [
        *[("::1", "/api/health")] * 3,
        ("::1", "/api/ready"),
    ]
    assert "live but not ready" in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure", [None, OSError("offline"), http.client.HTTPException("invalid response")]
)
def test_http_probe_closes_connection_on_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, failure: Exception | None
) -> None:
    connection = Mock()
    connection.request.side_effect = failure
    connection.getresponse.return_value.status = 200
    factory = Mock(return_value=connection)
    monkeypatch.setattr(cli.http.client, "HTTPConnection", factory)

    settings = RuntimeSettings.model_validate(
        {"OVERTURE_HOST": "localhost", "OVERTURE_PORT": 9876}
    )
    monkeypatch.setattr(cli.time, "monotonic", Mock(side_effect=[0, 60]))
    if failure is None:
        cli.probe(settings)
    else:
        with pytest.raises(ValueError, match="within 60 seconds"):
            cli.probe(settings)

    assert factory.call_count == (2 if failure is None else 1)
    factory.assert_called_with("localhost", 9876, timeout=5)
    assert connection.request.call_args_list[0].args == ("GET", "/api/health")
    assert connection.close.call_count == factory.call_count
    if failure is None:
        assert connection.request.call_args_list[1].args == ("GET", "/api/ready")
        assert connection.getresponse.return_value.read.call_count == 2


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (str(ip_address(0)), "127.0.0.1"),
        ("localhost", "localhost"),
        ("127.0.0.2", "127.0.0.2"),
    ],
)
def test_probe_ready_uses_the_local_listening_address(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    host: str,
    expected: str,
) -> None:
    status = Mock(return_value=200)
    monkeypatch.setattr(cli, "_status", status)
    cli.probe(RuntimeSettings.model_validate({"OVERTURE_HOST": host}))
    assert [call.args for call in status.call_args_list] == [
        (expected, cli.PORT, "/api/health"),
        (expected, cli.PORT, "/api/ready"),
    ]
    assert "Overture is ready" in capsys.readouterr().out


def test_probe_times_out_without_querying_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = Mock(return_value=None)
    monkeypatch.setattr(cli, "_status", status)
    monkeypatch.setattr(cli.time, "monotonic", Mock(side_effect=[0, 60]))
    with pytest.raises(ValueError, match="within 60 seconds"):
        cli.probe(RuntimeSettings())
    assert status.call_count == 1
    assert status.call_args.args[2] == "/api/health"


def test_serve_passes_owned_runtime_and_logging_to_uvicorn(
    database: Database,
    tmp_path: Path,
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = make_runtime(
        config_dir=tmp_path, app_config=app_config, database=database
    )
    build = Mock(return_value=runtime)
    configure = Mock()
    application = object()
    create = Mock(return_value=application)
    run = Mock()
    monkeypatch.setattr(cli, "build_runtime", build)
    monkeypatch.setattr(cli, "configure_logging", configure)
    monkeypatch.setattr(cli, "create_app", create)
    monkeypatch.setattr(cli.uvicorn, "run", run)

    cli.serve(app_config)

    build.assert_called_once_with(app_settings=app_config)
    configure.assert_called_once_with(app_config, runtime.redactor)
    create.assert_called_once_with(runtime)
    run.assert_called_once_with(
        application,
        host=app_config.OVERTURE_HOST,
        port=app_config.OVERTURE_PORT,
        proxy_headers=False,
        timeout_graceful_shutdown=20,
        log_config=None,
        access_log=False,
    )


def test_setup_switches_from_password_to_oidc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "overture.env"
    write_configuration(
        path,
        {"APP_PASSWORD_HASH": hash_password("old"), "MEDIA_SERVER_API_KEY": "old-key"},
    )
    answers = iter(
        [
            "plex",
            "http://127.0.0.1:32400",
            "oidc",
            "https://issuer.test",
            "client",
            "https://overture.test",
            "",
            "",
        ]
    )
    secrets = iter(["", "client-secret"])
    monkeypatch.setattr("builtins.input", Mock(side_effect=answers))
    monkeypatch.setattr(cli, "prompt_secret", Mock(side_effect=secrets))

    cli.main(["setup", "--config-file", str(path)])

    saved = read_configuration(path)
    assert "APP_PASSWORD_HASH" not in saved
    assert saved["OIDC_ISSUER_URL"] == "https://issuer.test"
    assert saved["OIDC_CLIENT_SECRET"] == "client-secret"
    assert saved["MEDIA_SERVER_API_KEY"] == "old-key"


@pytest.mark.parametrize("method", ["invalid", "password"])
def test_invalid_auth_choice_does_not_overwrite_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    path = tmp_path / "overture.env"
    path.write_text("MEDIA_SERVER=plex\n")
    original = path.read_bytes()
    answers = iter(["plex", "http://127.0.0.1:32400", method])
    monkeypatch.setattr("builtins.input", Mock(side_effect=answers))
    monkeypatch.setattr(cli, "prompt_secret", Mock(return_value="key"))
    monkeypatch.setenv("OIDC_CLIENT_ID", "inherited")
    with pytest.raises(
        SystemExit, match=r"Choose password or oidc|Unset OIDC credentials"
    ):
        cli.main(["setup", "--config-file", str(path)])
    assert path.read_bytes() == original


def test_explicit_missing_config_is_rejected_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load = Mock()
    monkeypatch.setattr(cli, "load_configuration", load)
    with pytest.raises(SystemExit, match="configuration file does not exist"):
        cli.main(["check", "--config-file", str(tmp_path / "missing")])
    load.assert_not_called()


@pytest.mark.parametrize("command", ["serve", "probe"])
def test_main_dispatches_valid_configuration(
    command: str, tmp_path: Path, app_config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "overture.env"
    path.touch()
    load = Mock(return_value=app_config)
    check = Mock()
    action = Mock()
    monkeypatch.setattr(cli, "load_configuration", load)
    monkeypatch.setattr(cli, "check", check)
    monkeypatch.setattr(cli, command, action)
    cli.main([command, "--config-file", str(path)])
    load.assert_called_once_with(
        RuntimeSettings if command == "probe" else Settings, path.resolve()
    )
    action.assert_called_once_with(app_config)
    assert check.call_count == int(command == "serve")


@pytest.mark.parametrize("head", [None, "revision"])
def test_check_requires_a_migration_head(
    tmp_path: Path,
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    head: str | None,
) -> None:
    (tmp_path / "index.html").touch()
    monkeypatch.setattr(cli, "verify_config_dir", Mock())
    monkeypatch.setattr(cli, "verify_theme_tools", Mock())
    monkeypatch.setattr(cli, "FRONTEND_DIR", tmp_path)
    monkeypatch.setattr(
        cli.ScriptDirectory,
        "from_config",
        Mock(return_value=Mock(get_current_head=Mock(return_value=head))),
    )
    if head is None:
        with pytest.raises(ValueError, match="migrations are missing"):
            cli.check(app_config)
    else:
        cli.check(app_config)
