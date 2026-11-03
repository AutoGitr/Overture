"""Exercise the public runtime boundary of a built Overture container."""

lazy import argparse
lazy import http.client
lazy import json
lazy import re
lazy import shutil
lazy import sqlite3
lazy import subprocess
lazy import tempfile
lazy from http.cookies import SimpleCookie
lazy from importlib.metadata import distribution
lazy from pathlib import Path
lazy from typing import Any

lazy from websockets.sync.client import connect

lazy from overture.config import PORT, RuntimeSettings, load_configuration
lazy from overture.migrations import versions_at_head
lazy from overture.runtime_paths import database_path

HOST = "127.0.0.1"
ORIGIN = f"http://{HOST}:{PORT}"


def verify_frontend() -> None:
    """Serve both the HTML shell and its packaged application module."""
    connection = http.client.HTTPConnection(HOST, PORT, timeout=10)
    try:
        connection.request("GET", "/", headers={"Accept": "text/html"})
        response = connection.getresponse()
        html = response.read().decode()
        assert response.status == 200
        assert "text/html" in response.headers.get("Content-Type", "")
        module = re.search(r'src="(/assets/[^"\s]+\.js)"', html)
        assert module is not None, "Packaged frontend module is missing"
        connection.request("GET", module.group(1))
        asset = connection.getresponse()
        assert asset.status == 200
        assert asset.read(), "Packaged frontend module is empty"
    finally:
        connection.close()


def verify_theme_tools() -> None:
    """Exercise media tools under the container's actual user and filesystem rules."""
    for package in ("yt-dlp", "yt-dlp-ejs", "Pillow"):
        assert distribution(package).files, f"Missing package inventory: {package}"

    deno, ffmpeg, ffprobe = (
        shutil.which(name) for name in ("deno", "ffmpeg", "ffprobe")
    )
    assert deno, "Deno must be on PATH"
    assert ffmpeg, "FFmpeg must be on PATH"
    assert ffprobe, "ffprobe must be on PATH"

    subprocess.run(
        [
            deno,
            "run",
            "--no-prompt",
            "--no-config",
            "--no-lock",
            "--cached-only",
            "-",
        ],
        input=(
            'for (const name of ["read", "write", "net", "env", "run", "ffi"]) {'
            ' if ((await Deno.permissions.query({name})).state === "granted")'
            " throw new Error(`Unexpected ${name} permission`); }"
        ),
        text=True,
        check=True,
        timeout=30,
    )
    with tempfile.TemporaryDirectory() as directory:
        audio = str(Path(directory) / "theme.mp3")
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                audio,
            ],
            check=True,
            timeout=30,
        )
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name:format=duration",
                "-of",
                "json",
                audio,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        metadata = json.loads(probe.stdout)
        assert metadata["streams"][0]["codec_name"] == "mp3", metadata
        assert 1 <= float(metadata["format"]["duration"]) < 2, metadata


class Session:
    """Small HTTP session that retains the two application cookies."""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    @property
    def cookie_header(self) -> str:
        return "; ".join(f"{name}={value}" for name, value in self.cookies.items())

    def request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        csrf: bool = False,
    ) -> tuple[int, dict[str, str], Any]:
        headers = {"Accept": "application/json"}
        if self.cookies:
            headers["Cookie"] = self.cookie_header
        if csrf:
            headers["X-CSRF-Token"] = self.cookies["overture_csrf"]
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        connection = http.client.HTTPConnection(HOST, PORT, timeout=10)
        try:
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            content = response.read()
            for raw_cookie in response.headers.get_all("Set-Cookie", []):
                parsed = SimpleCookie()
                parsed.load(raw_cookie)
                for name, morsel in parsed.items():
                    if morsel["max-age"] == "0":
                        self.cookies.pop(name, None)
                    else:
                        self.cookies[name] = morsel.value
            payload = json.loads(content) if content else None
            headers_out = {
                name.lower(): value for name, value in response.headers.items()
            }
            return response.status, headers_out, payload
        finally:
            connection.close()


def expect_status(actual: int, expected: int, payload: object) -> None:
    if actual != expected:
        raise AssertionError(f"expected HTTP {expected}, got {actual}: {payload!r}")


def verify_database(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    finally:
        connection.close()
    assert integrity == ("ok",), integrity
    assert revision == (versions_at_head(),), revision


def verify_websocket(session: Session) -> None:
    with connect(
        f"ws://{HOST}:{PORT}/ws",
        origin=ORIGIN,
        additional_headers={"Cookie": session.cookie_header},
        open_timeout=10,
    ) as websocket:
        websocket.send(json.dumps({"event": "client.resync"}))
        envelope = json.loads(websocket.recv(timeout=10))
    assert envelope["event"] == "realtime.snapshot", envelope
    assert envelope["data"]["epoch"] == envelope["epoch"], envelope
    assert envelope["data"]["sequence"] == envelope["sequence"], envelope


def verify_runtime(
    *, expected_tab: str, set_tab: str | None, expected_version: str | None
) -> None:
    session = Session()

    status, headers, health = session.request("GET", "/api/health")
    expect_status(status, 200, health)
    assert health["status"] == "ok"
    if expected_version is not None:
        assert health["version"] == expected_version, health
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in headers["content-security-policy"]

    status, _headers, ready = session.request("GET", "/api/ready")
    expect_status(status, 200, ready)
    assert ready["status"] == "ready", ready
    assert all(ready["checks"].values()), ready

    status, _headers, anonymous = session.request("GET", "/api/auth/me")
    expect_status(status, 200, anonymous)
    assert anonymous == {"authenticated": False}
    status, _headers, denied = session.request("GET", "/api/settings")
    expect_status(status, 401, denied)

    status, _headers, login = session.request(
        "POST", "/api/auth/login", {"password": "smoke-password-long"}
    )
    expect_status(status, 200, login)
    assert login == {"status": "ok"}
    assert set(session.cookies) == {"overture_token", "overture_csrf"}

    status, _headers, current = session.request("GET", "/api/settings")
    expect_status(status, 200, current)
    assert current["workflow"] == expected_tab, current

    status, _headers, rejected = session.request(
        "PUT", "/api/settings", {"workflow": expected_tab}
    )
    expect_status(status, 403, rejected)
    verify_websocket(session)

    if set_tab is not None:
        status, _headers, updated = session.request(
            "PUT", "/api/settings", {"workflow": set_tab}, csrf=True
        )
        expect_status(status, 200, updated)
        assert updated["workflow"] == set_tab, updated

    status, _headers, rejected = session.request("POST", "/api/auth/logout")
    expect_status(status, 403, rejected)
    status, _headers, logout = session.request("POST", "/api/auth/logout", csrf=True)
    expect_status(status, 200, logout)
    assert logout.get("status") == "ok", logout
    assert not session.cookies


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=database_path(load_configuration(RuntimeSettings).OVERTURE_CONFIG_DIR),
    )
    parser.add_argument("--expected-tab", default="art")
    parser.add_argument("--expected-version")
    parser.add_argument("--set-tab")
    args = parser.parse_args()

    verify_theme_tools()
    verify_frontend()
    verify_database(args.database)
    verify_runtime(
        expected_tab=args.expected_tab,
        set_tab=args.set_tab,
        expected_version=args.expected_version,
    )


if __name__ == "__main__":
    main()
