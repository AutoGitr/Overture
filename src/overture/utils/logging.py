"""Process logging: one redacting handler on standard output.

The server entry point configures logging once, before uvicorn starts, so every
record - uvicorn's own included - leaves the process through the same format
and redaction. Importing or creating the application never changes logging.
"""

lazy import logging
lazy import sys
lazy from datetime import datetime, tzinfo
lazy from typing import override

lazy from ..config import Settings
lazy from .security import Redactor

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_LEVEL_COLOURS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        logging.DEBUG: _DIM,
        logging.INFO: "\x1b[32m",
        logging.WARNING: "\x1b[33m",
        logging.ERROR: "\x1b[31m",
        logging.CRITICAL: "\x1b[1;31m",
    }
)


class LogFormatter(logging.Formatter):
    """Render ``<time> <LEVEL> [<logger>] <message>`` with secrets redacted.

    Times are in the configured timezone. The message, traceback and stack are
    redacted once, as the finished text, which is the single redaction boundary
    for logs. *colour* styles the prefix for an interactive terminal.
    """

    def __init__(self, *, timezone: tzinfo, redactor: Redactor, colour: bool) -> None:
        super().__init__()
        self._timezone = timezone
        self._redactor = redactor
        self._colour = colour

    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, self._timezone).strftime(
            datefmt or "%Y-%m-%d %H:%M:%S"
        )

    @override
    def format(self, record: logging.LogRecord) -> str:
        time = self.formatTime(record)
        level = f"{record.levelname:<8}"
        name = f"[{record.name.removeprefix('overture.')}]"
        body = self._redactor.text(super().format(record))
        if self._colour:
            colour = _LEVEL_COLOURS.get(record.levelno, "")
            return (
                f"{_DIM}{time}{_RESET} {colour}{level}{_RESET} "
                f"{_DIM}{name}{_RESET} {body}"
            )
        return f"{time} {level} {name} {body}"


def configure_logging(config: Settings, redactor: Redactor) -> None:
    """Route every record through one redacting handler on standard output.

    Libraries log at ``WARNING`` and above, so the log shows what Overture did
    rather than how its dependencies did it. ``debug`` also shows outgoing HTTP
    requests, migrations and uvicorn's server lifecycle; transport and SQLite
    driver traces stay off, as they log several lines per call.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        LogFormatter(
            timezone=config.tzinfo,
            redactor=redactor,
            colour=config.LOG_COLOUR,
        )
    )
    logging.basicConfig(level=config.LOG_LEVEL.upper(), handlers=[handler], force=True)
    verbose = logging.DEBUG if config.LOG_LEVEL == "debug" else logging.WARNING
    for name, level in {
        "alembic": verbose,
        "httpx2": verbose,
        "uvicorn": verbose,
        "aiosqlite": logging.WARNING,
        "httpcore2": logging.WARNING,
        "PIL": logging.WARNING,
    }.items():
        logging.getLogger(name).setLevel(level)
