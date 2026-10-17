"""Time helpers for UTC storage and app-local scheduling/display."""

lazy import re
lazy from datetime import UTC, datetime, tzinfo
lazy from typing import Any

_EXCESS_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return utc_now().isoformat()


def utc_now() -> datetime:
    """Return the current aware UTC datetime."""
    return datetime.now(UTC)


def format_duration(seconds: float) -> str:
    """Return a short duration for people: ``0.4s``, ``12s``, ``3m 05s``, ``2h 01m``."""
    if seconds < 10:
        return f"{max(seconds, 0):.1f}s"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def parse_utc_datetime(value: Any, *, naive_tz: tzinfo = UTC) -> datetime | None:
    """Parse a timestamp and return an aware UTC datetime."""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except OverflowError, OSError, ValueError:
            return None

    text = str(value).strip()
    if not text:
        return None

    try:
        if text.lstrip("-").isdigit():
            return datetime.fromtimestamp(int(text), tz=UTC)
    except OverflowError, OSError, ValueError:
        return None

    normalized = _EXCESS_FRACTION_RE.sub(r"\1", text)

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_tz)

    return parsed.astimezone(UTC)
