"""The ``overture`` command: serving, checks and local administration."""

lazy import argparse
lazy import getpass
lazy import http.client
lazy import importlib.util
lazy import os
lazy import shutil
lazy import subprocess
lazy import sys
lazy import tempfile
lazy import time
lazy import warnings
lazy from ipaddress import ip_address
lazy from pathlib import Path

lazy import uvicorn
lazy from alembic.script import ScriptDirectory
lazy from alembic.util.exc import CommandError
lazy from pydantic import ValidationError

lazy from .config import (
    HOST,
    PORT,
    RuntimeSettings,
    Settings,
    configuration_file,
    load_configuration,
    read_configuration,
    write_configuration,
)
lazy from .db.session import alembic_config
lazy from .main import create_app
lazy from .passwords import hash_password
lazy from .runtime import build_runtime
lazy from .runtime_paths import FRONTEND_DIR
lazy from .services.themes.youtube_resolver import THEME_PACKAGES, THEME_TOOLS
lazy from .utils.logging import configure_logging
lazy from .utils.security import sanitise_error
lazy from .version import APP_VERSION


class Arguments(argparse.Namespace):
    """Typed parser destinations."""

    command: str = "serve"
    config_file: Path | None = None
    password_stdin: bool = False


def parser() -> argparse.ArgumentParser:
    """Allow the configuration file option before or after a command."""
    options = argparse.ArgumentParser(
        add_help=False, argument_default=argparse.SUPPRESS
    )
    options.add_argument("--config-file", type=Path)
    root = argparse.ArgumentParser(prog="overture", parents=[options])
    root.add_argument("--version", action="version", version=APP_VERSION)
    commands = root.add_subparsers(dest="command")
    root.set_defaults(command="serve")
    commands.add_parser("serve", parents=[options], help="Run the server (default)")
    commands.add_parser(
        "check", parents=[options], help="Check prerequisites without starting"
    )
    commands.add_parser("setup", parents=[options], help="Create the configuration")
    commands.add_parser(
        "probe", parents=[options], help="Wait for the running service to answer"
    )
    password = commands.add_parser("password", help="Generate a password hash")
    hash_parser = password.add_subparsers(required=True).add_parser("hash")
    hash_parser.add_argument(
        "--password-stdin",
        action="store_true",
        dest="password_stdin",
        help="Read the password from standard input without terminal prompts",
    )
    return root


def prompt_secret(label: str) -> str:
    """Refuse getpass's echoing fallback if the terminal cannot hide input."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(label)


def saved_secret(label: str, current: str) -> str:
    """Ask for a secret, keeping the saved one on empty input."""
    suffix = " [Enter keeps the saved value]" if current else ""
    return prompt_secret(f"{label}{suffix}: ") or current


def new_password(current: str = "") -> str:
    """Ask for a new password without retaining plaintext beyond hashing."""
    hint = (
        "Enter keeps the saved password"
        if current
        else "15+ characters recommended; symbols optional"
    )
    password = prompt_secret(f"Password ({hint}): ")
    if current and not password:
        return current
    if password != prompt_secret("Repeat password: "):
        raise ValueError("Passwords do not match; no changes were saved.")
    return hash_password(password)


def prompt(label: str, default: str = "") -> str:
    """Read an ordinary setting, preserving an existing value on empty input."""
    suffix = f" [{default}]" if default else ""
    return input(f"{label}{suffix}: ").strip() or default


def setup(path: Path) -> None:
    """Collect and validate all required configuration before saving it."""
    values = read_configuration(path)
    values["MEDIA_SERVER"] = prompt(
        "Media server (plex/jellyfin/emby)", values.get("MEDIA_SERVER", "plex")
    )
    values["MEDIA_SERVER_URL"] = prompt(
        "Media server URL", values.get("MEDIA_SERVER_URL", "")
    )
    values["MEDIA_SERVER_API_KEY"] = saved_secret(
        "Media server API key", values.get("MEDIA_SERVER_API_KEY", "")
    )
    default_auth = values.get(
        "AUTH_MODE", "oidc" if values.get("OIDC_ISSUER_URL") else "password"
    )
    method = prompt("Authentication (password/oidc)", default_auth).lower()
    if method not in {"password", "oidc"}:
        raise ValueError("Choose password or oidc.")
    values["AUTH_MODE"] = method
    if method == "password":
        if any(
            os.environ.get(key)
            for key in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
        ):
            raise ValueError(
                "Unset OIDC credentials in the environment "
                "before selecting password login."
            )
        for key in tuple(values):
            if key.startswith("OIDC_"):
                values.pop(key)
        values["APP_PASSWORD_HASH"] = new_password(values.get("APP_PASSWORD_HASH", ""))
    else:
        values.pop("APP_PASSWORD_HASH", None)
        for key, label in (
            ("OIDC_ISSUER_URL", "OIDC issuer URL"),
            ("OIDC_CLIENT_ID", "OIDC client ID"),
            ("APP_URL", "Public HTTPS Overture URL"),
        ):
            values[key] = prompt(label, values.get(key, ""))
        values["OIDC_CLIENT_SECRET"] = saved_secret(
            "OIDC client secret", values.get("OIDC_CLIENT_SECRET", "")
        )
    values["OVERTURE_HOST"] = prompt(
        "Listening address", values.get("OVERTURE_HOST", HOST)
    )
    values["OVERTURE_PORT"] = prompt(
        "Listening port", values.get("OVERTURE_PORT", str(PORT))
    )
    # Validate only the collected values.
    Settings.model_validate(values)
    write_configuration(path, values)
    print("Configuration saved. Run overture check before starting the service.")


def verify_config_dir(config_dir: Path) -> None:
    """Require a config directory this process can create files in."""
    if not config_dir.is_dir():
        raise ValueError(
            f"Config directory does not exist: {config_dir}. Create it first."
        )
    if not (os.access(config_dir, os.W_OK) and os.access(config_dir, os.X_OK)):
        uid = getattr(os, "getuid", lambda: -1)()
        gid = getattr(os, "getgid", lambda: -1)()
        raise ValueError(
            f"Config directory {config_dir} is not writable by UID={uid} GID={gid}."
        )
    with tempfile.TemporaryFile(dir=config_dir) as stream:
        stream.write(b"Overture filesystem check")
        stream.flush()


def verify_theme_tools() -> None:
    """Require every program and package theme downloads use."""
    for tool, flag in THEME_TOOLS.items():
        if not shutil.which(tool):
            raise ValueError(
                f"{tool} is not installed or not in PATH. Reinstall Overture."
            )
        try:
            subprocess.run(
                [tool, flag],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(
                f"{tool} failed execution check. Reinstall Overture."
            ) from exc
    for package in THEME_PACKAGES:
        if importlib.util.find_spec(package) is None:
            raise ValueError(f"The {package} package is missing. Reinstall Overture.")


def check(settings: Settings) -> None:
    """Check installation prerequisites without constructing the runtime."""
    verify_config_dir(settings.OVERTURE_CONFIG_DIR)
    verify_theme_tools()
    if not (FRONTEND_DIR / "index.html").is_file():
        raise ValueError(
            "The frontend is missing; reinstall the complete Overture release."
        )
    try:
        head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    except (CommandError, OSError) as exc:
        raise ValueError(
            "The installed database migrations are damaged. Reinstall Overture."
        ) from exc
    if not head:
        raise ValueError(
            "The installed database migrations are missing. Reinstall Overture."
        )


def serve(settings: Settings) -> None:
    """Configure logging once and hand the owned runtime to uvicorn."""
    runtime = build_runtime(app_settings=settings)
    configure_logging(settings, runtime.redactor)
    uvicorn.run(
        create_app(runtime),
        host=settings.OVERTURE_HOST,
        port=settings.OVERTURE_PORT,
        proxy_headers=False,
        timeout_graceful_shutdown=20,
        log_config=None,
        access_log=False,
    )


def _status(host: str, port: int, path: str) -> int | None:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
    except OSError, http.client.HTTPException:
        return None
    else:
        return response.status
    finally:
        connection.close()


def probe(settings: RuntimeSettings) -> None:
    """Wait up to a minute for liveness, then report readiness."""
    host = settings.OVERTURE_HOST
    if host != "localhost" and ip_address(host).is_unspecified:
        host = "::1" if host == "::" else "127.0.0.1"
    deadline = time.monotonic() + 60
    while _status(host, settings.OVERTURE_PORT, "/api/health") != 200:
        if time.monotonic() >= deadline:
            raise ValueError("The service did not become live within 60 seconds.")
        time.sleep(1)
    if _status(host, settings.OVERTURE_PORT, "/api/ready") == 200:
        print("Overture is ready. Check media-server connectivity in Settings.")
    else:
        print("Overture is live but not ready. Check journalctl -u overture.")


def main(argv: list[str] | None = None) -> None:
    """Dispatch administration without starting runtime services."""
    args = parser().parse_args(argv, namespace=Arguments())
    try:
        if args.command == "password":
            if args.password_stdin:
                line = sys.stdin.readline()
                if not line:
                    raise ValueError("Password from stdin must not be empty.")
                encoded = hash_password(line.rstrip("\r\n"))
            else:
                encoded = new_password()
            print(f"APP_PASSWORD_HASH='{encoded}'")
            return
        path = (args.config_file or configuration_file()).expanduser().resolve()
        if (
            args.config_file is not None
            and args.command != "setup"
            and not path.is_file()
        ):
            raise ValueError(
                "The configuration file does not exist. Run overture setup."
            )
        if args.command == "setup":
            setup(path)
        elif args.command == "probe":
            probe(load_configuration(RuntimeSettings, path))
        else:
            settings = load_configuration(Settings, path)
            check(settings)
            if args.command == "serve":
                serve(settings)
            else:
                print(
                    "Configuration, resources, permissions and dependencies are valid."
                )
    except KeyboardInterrupt, EOFError:
        sys.exit("Cancelled.")
    except (OSError, ValueError, ValidationError, getpass.GetPassWarning) as exc:
        sys.exit(sanitise_error(str(exc)))
