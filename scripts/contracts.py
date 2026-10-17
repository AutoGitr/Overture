"""Generate, or check, every contract the frontend reads from the backend.

This is the one entry point: the OpenAPI schema, the WebSocket payload types,
the settings defaults, and (through Bun) the REST client generated from the
schema.
"""

lazy import argparse
lazy import json
lazy import os
lazy import subprocess
lazy import sys
lazy from collections.abc import Callable
lazy from pathlib import Path
lazy from typing import Any

lazy from overture.main import create_app
lazy from scripts.generate_settings_defaults import render_settings_defaults
lazy from scripts.generate_ws_types import render_ws_types

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
REGENERATE_HINT = (
    "Run `uv run python -m scripts.contracts` from the repository root "
    "to regenerate generated contracts."
)

#: Rendering the OpenAPI schema boots the app, which validates configuration.
#: Placeholders shaped to satisfy validation and nothing more: this build step
#: never talks to a media server.
BUILD_ENVIRONMENT = frozendict(
    {
        "APP_PASSWORD_HASH": (
            "$argon2id$v=19$m=19456,t=2,p=1$Y96qqNb5fWisYsjxPJH7rw$"
            "tmT2xh96T8fz3H2p6jD3VzxKyFZzHeUFucJGxjvSlM0"
        ),
        "MEDIA_SERVER": "plex",
        "MEDIA_SERVER_URL": "http://127.0.0.1:32400",
        "MEDIA_SERVER_API_KEY": "x" * 32,
    }
)


def render_openapi_schema() -> str:
    """Render the FastAPI OpenAPI schema as stable JSON text."""
    schema: dict[str, Any] = create_app().openapi()
    return f"{json.dumps(schema, sort_keys=True, indent=2)}\n"


#: Each generated file and what renders it, in dependency order: the WebSocket
#: types import the REST models the OpenAPI schema names.
OUTPUTS: tuple[tuple[Path, Callable[[], str]], ...] = (
    (ROOT_DIR / "openapi" / "overture.json", render_openapi_schema),
    (FRONTEND_DIR / "src" / "generated" / "ws.ts", render_ws_types),
    (FRONTEND_DIR / "src" / "generated" / "settings.ts", render_settings_defaults),
)


def _write_or_check(path: Path, content: str, *, check: bool) -> bool:
    """Write *content* to *path*, or report whether the file already holds it."""
    if check:
        return path.exists() and path.read_text() == content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, newline="\n")
    return True


def _rest_client(*, check: bool) -> int:
    command = ["bun", "scripts/generate-rest-client.ts"]
    if check:
        command.append("--check")
    try:
        return subprocess.run(command, cwd=FRONTEND_DIR, check=False).returncode
    except FileNotFoundError:
        print(
            "bun is required to generate the frontend REST client. "
            "Install Bun and run `bun install --frozen-lockfile` in frontend.",
            file=sys.stderr,
        )
        return 127


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="Verify the files are current."
    )
    args = parser.parse_args()
    for name, value in BUILD_ENVIRONMENT.items():
        os.environ.setdefault(name, value)

    stale = [
        path
        for path, render in OUTPUTS
        if not _write_or_check(path, render(), check=args.check)
    ]
    for path in stale:
        print(
            f"stale generated contract: {path.relative_to(ROOT_DIR)}", file=sys.stderr
        )
    result = 1 if stale else _rest_client(check=args.check)
    if result and args.check:
        print(REGENERATE_HINT, file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
