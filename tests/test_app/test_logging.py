"""Process logging: one redacting, timezone-aware handler on standard output."""

lazy import io
lazy import logging
lazy import sys
lazy from collections.abc import Generator
lazy from contextlib import contextmanager
lazy from datetime import UTC
lazy from zoneinfo import ZoneInfo

lazy import pytest

lazy from overture.config import Settings
lazy from overture.utils.logging import LogFormatter, configure_logging
lazy from overture.utils.security import Redactor

_LIBRARIES = ("alembic", "httpx2", "uvicorn", "aiosqlite", "httpcore2", "PIL")


def _record(
    message: str,
    *args: object,
    level: int = logging.INFO,
    exc: BaseException | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        "overture.services.sync.engine",
        level,
        __file__,
        1,
        message,
        args,
        (type(exc), exc, exc.__traceback__) if exc is not None else None,
    )
    record.created = 0.0
    return record


def test_a_line_has_local_time_level_and_short_logger_name() -> None:
    formatter = LogFormatter(
        timezone=ZoneInfo("Europe/Stockholm"), redactor=Redactor(()), colour=False
    )

    line = formatter.format(_record("Synced %d items", 3))

    assert line == "1970-01-01 01:00:00 INFO     [services.sync.engine] Synced 3 items"


def test_message_arguments_and_traceback_are_redacted() -> None:
    secret = "configured-secret-value"
    formatter = LogFormatter(timezone=UTC, redactor=Redactor([secret]), colour=False)
    try:
        raise ValueError(f"upstream rejected {secret}")
    except ValueError as exc:
        error = exc

    line = formatter.format(
        _record("Calling %s?api_key=abc123", f"http://host/{secret}", exc=error)
    )

    assert "Traceback" in line
    assert secret not in line
    assert "abc123" not in line


def test_colour_styles_the_prefix_and_leaves_the_message_alone() -> None:
    formatter = LogFormatter(timezone=UTC, redactor=Redactor(()), colour=True)

    line = formatter.format(_record("plain message", level=logging.WARNING))

    assert "\x1b[33mWARNING \x1b[0m" in line
    assert line.endswith("\x1b[0m plain message")


@contextmanager
def _isolated_logging() -> Generator[None]:
    """Restore the root handlers and library levels the test changes."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    levels = {name: logging.getLogger(name).level for name in _LIBRARIES}
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        for name, library_level in levels.items():
            logging.getLogger(name).setLevel(library_level)


@pytest.mark.parametrize(
    ("log_level", "root_level", "verbose"),
    [
        ("info", logging.INFO, logging.WARNING),
        ("debug", logging.DEBUG, logging.DEBUG),
    ],
)
def test_every_record_goes_through_one_handler_on_standard_output(
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    log_level: str,
    root_level: int,
    verbose: int,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    config = app_config.model_copy(update={"LOG_LEVEL": log_level, "LOG_COLOUR": False})

    with _isolated_logging():
        configure_logging(config, Redactor(()))
        root = logging.getLogger()
        [handler] = root.handlers
        configured_level = root.level
        library_levels = {name: logging.getLogger(name).level for name in _LIBRARIES}
        logging.getLogger("uvicorn.error").error("from uvicorn")

    assert isinstance(handler.formatter, LogFormatter)
    assert configured_level == root_level
    assert library_levels == {
        "alembic": verbose,
        "httpx2": verbose,
        "uvicorn": verbose,
        "aiosqlite": logging.WARNING,
        "httpcore2": logging.WARNING,
        "PIL": logging.WARNING,
    }
    assert "ERROR    [uvicorn.error] from uvicorn" in stream.getvalue()


@pytest.mark.parametrize("colour", [True, False])
def test_colour_follows_the_setting_even_without_a_terminal(
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    *,
    colour: bool,
) -> None:
    """A container's stdout is no terminal, yet its log viewer renders colour."""
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)

    with _isolated_logging():
        configure_logging(
            app_config.model_copy(update={"LOG_COLOUR": colour}), Redactor(())
        )
        logging.getLogger("overture.http").warning("refused")

    assert ("\x1b[33mWARNING \x1b[0m" in stream.getvalue()) is colour
