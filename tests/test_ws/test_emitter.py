"""Coverage for WebSocketEventEmitter payload validation delegation."""

lazy from typing import Any

lazy import pytest

lazy from overture.jobs.progress_log import JobOutcome, log_entry
lazy from overture.utils.types import JsonValue
lazy from overture.ws.connection_manager import (
    ConnectionManager,
    EventBuilder,
    ProjectionUpdater,
)
lazy from overture.ws.emitter import WebSocketEventEmitter


def _emitter(
    monkeypatch: pytest.MonkeyPatch, *, broadcast_built_result: bool = True
) -> tuple[WebSocketEventEmitter, dict[str, Any]]:
    """Build a real ConnectionManager with its network-facing methods stubbed.

    A real instance is used (rather than a duck-typed fake) so it satisfies
    WebSocketEventEmitter's concrete `ConnectionManager` constructor type
    under static type checking.
    """
    manager = ConnectionManager()
    recorded: dict[str, Any] = {"broadcast": []}

    async def fake_broadcast(
        event: str,
        data: JsonValue = None,
        *,
        before_publish: ProjectionUpdater | None = None,
    ) -> None:
        recorded["broadcast"].append(
            {"event": event, "data": data, "before_publish": before_publish}
        )

    async def fake_broadcast_built(builder: EventBuilder) -> bool:
        built = builder()
        if built is None:
            return False
        return broadcast_built_result

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)
    monkeypatch.setattr(manager, "broadcast_built", fake_broadcast_built)

    return WebSocketEventEmitter(manager), recorded


async def test_broadcast_validates_payload_and_delegates_to_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitter, recorded = _emitter(monkeypatch)

    await emitter.broadcast("ping")

    assert recorded["broadcast"] == [
        {"event": "ping", "data": None, "before_publish": None}
    ]


async def test_broadcast_built_returns_false_when_builder_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitter, _recorded = _emitter(monkeypatch)

    result = await emitter.broadcast_built(lambda: None)

    assert result is False


async def test_broadcast_built_validates_and_returns_manager_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitter, _recorded = _emitter(monkeypatch, broadcast_built_result=True)

    result = await emitter.broadcast_built(lambda: ("ping", None))

    assert result is True


async def test_emitter_is_the_redaction_boundary_for_typed_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payloads are redacted once, here, before anything reaches the socket.

    The connection layer transports whatever it is handed, so a secret that
    survives this call survives all the way to the browser.
    """
    emitter, recorded = _emitter(monkeypatch)

    await emitter.broadcast(
        "match.progress",
        {
            "job": {"kind": "bulk_art", "status": "progress"},
            "log": log_entry(JobOutcome.ERROR, "Movie", "token=hunter2"),
        },
    )

    delivered = recorded["broadcast"][0]["data"]
    assert "hunter2" not in str(delivered)
    assert "[REDACTED]" in str(delivered)
