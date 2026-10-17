"""Each HTTP request is one log line that never leaks request inputs."""

lazy import logging
lazy import re
lazy from datetime import UTC

lazy import pytest
lazy from _pytest.logging import LogCaptureFixture
lazy from fastapi import FastAPI
lazy from fastapi.testclient import TestClient
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from overture.utils.logging import LogFormatter
lazy from overture.utils.request_logging import request_log_level
lazy from overture.utils.security import Redactor


def _http_records(caplog: LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "overture.http"]


@pytest.mark.parametrize(
    ("method", "path", "status", "level"),
    [
        ("GET", "/api/library/items", 500, logging.ERROR),
        ("GET", "/api/health", 503, logging.ERROR),
        ("POST", "/api/sync", 403, logging.WARNING),
        ("POST", "/api/auth/login", 429, logging.WARNING),
        ("POST", "/api/auth/login", 401, logging.INFO),
        ("GET", "/api/library/items/1", 404, logging.INFO),
        ("POST", "/api/sync", 202, logging.INFO),
        ("DELETE", "/api/backup/1", 204, logging.INFO),
        ("GET", "/api/library/items", 200, logging.DEBUG),
        ("GET", "/api/health", 200, logging.DEBUG),
        ("GET", "/api/library/items/1/local-image/poster", 404, logging.DEBUG),
        ("GET", "/assets/index.js", 200, logging.DEBUG),
        ("GET", "/wp-login.php", 404, logging.DEBUG),
    ],
)
def test_request_level_follows_what_the_request_means(
    method: str, path: str, status: int, level: int
) -> None:
    assert request_log_level(method, path, status) == level


def test_a_read_is_one_debug_line_without_query_string_or_request_id(
    client: TestClient,
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="overture.http")

    response = client.get(
        "/api/auth/me?password=must-not-appear",
        headers={"X-Request-ID": "request-123"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    [record] = _http_records(caplog)
    assert record.levelno == logging.DEBUG
    assert re.fullmatch(r"GET /api/auth/me -> 200 in \d+\.\d ms", record.getMessage())


def test_a_failed_request_names_its_request_id(
    client: TestClient,
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="overture.http")

    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    request_id = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{8}", request_id)
    [record] = _http_records(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage().endswith(f" (request {request_id})")


def test_csrf_rejections_are_tagged_and_logged_as_warnings(
    client: TestClient,
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="overture.http")

    response = client.post("/api/auth/logout", headers={"X-Request-ID": "rid-csrf"})

    assert response.status_code == 403
    assert response.headers["X-Request-ID"] == "rid-csrf"
    [record] = _http_records(caplog)
    assert record.levelno == logging.WARNING
    assert "POST /api/auth/logout -> 403" in record.getMessage()
    assert record.getMessage().endswith("(request rid-csrf)")


@pytest.mark.parametrize("supplied", ["two words", "x" * 65, "id;drop", ""])
def test_a_supplied_request_id_that_is_not_a_plain_token_is_replaced(
    client: TestClient, supplied: str
) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": supplied})

    assert re.fullmatch(r"[0-9a-f]{8}", response.headers["X-Request-ID"])


def test_a_decoded_control_character_cannot_reach_the_log(
    client: TestClient,
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="overture.http")

    # A terminal escape sequence decoded from the path would restyle or clear
    # the operator's terminal; it is logged percent-encoded instead.
    client.get("/api/x%1B%5B2Jforged")

    [record] = _http_records(caplog)
    assert "\x1b" not in record.getMessage()
    assert record.getMessage().startswith("GET /api/x%1B%5B2Jforged -> 404 in ")


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("boom: token=secret-12345"),
        SQLAlchemyError("database disk image is malformed: token=secret-12345"),
    ],
)
def test_an_unhandled_error_is_one_redacted_error_line_with_its_traceback(
    test_app: FastAPI,
    client: TestClient,
    caplog: LogCaptureFixture,
    error: Exception,
) -> None:
    async def explode() -> None:
        raise error

    test_app.add_api_route("/api/explode", explode, methods=["GET"])
    caplog.set_level(logging.DEBUG)

    response = client.get("/api/explode", headers={"X-Request-ID": "failure-123"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["X-Request-ID"] == "failure-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    [record] = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert record.name == "overture.http"
    assert record.exc_info is not None
    assert record.exc_info[1] is error
    line = LogFormatter(timezone=UTC, redactor=Redactor(()), colour=False).format(
        record
    )
    assert "GET /api/explode -> 500 in " in line
    assert line.splitlines()[0].endswith("(request failure-123)")
    assert "Traceback" in line
    assert "secret-12345" not in line
