"""WebSocket connection manager behavior."""

lazy import asyncio
lazy import json
lazy from collections.abc import Coroutine, Mapping
lazy from contextvars import Context
lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from uvicorn import Config

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.protocols import ClientConnection
lazy from overture.utils.time import parse_utc_datetime, utc_now
lazy from overture.utils.types import JsonValue
lazy from overture.ws import resync
lazy from overture.ws.connection_manager import ConnectionManager, SnapshotBuilder
lazy from tests.conftest import FakeMediaServerProvider, FakeWebSocket
lazy from tests.runtime_helpers import NoopProviderRegistry, make_runtime


async def test_connect_broadcast_and_disconnect(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    manager = ConnectionManager()
    websocket = fake_websocket_factory()

    await manager.connect(websocket)
    assert websocket.accepted is True
    assert manager.active_connections == 1

    await manager.broadcast("schedules.changed", {"kind": "sync"})
    await asyncio.sleep(0)
    message = json.loads(websocket.sent_text[0])
    assert message["epoch"] == manager.epoch
    assert message["sequence"] == 1
    assert message["event"] == "schedules.changed"
    assert message["data"] == {"kind": "sync"}

    manager.disconnect(websocket)
    assert manager.active_connections == 0


async def test_connection_writer_uses_supported_event_loop_arguments(
    monkeypatch: pytest.MonkeyPatch,
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    loop = asyncio.get_running_loop()
    original_create_task = loop.create_task

    # uvloop 0.22.1, used by Uvicorn in the Linux image, has this signature.
    def create_task[T](
        coro: Coroutine[Any, Any, T],
        *,
        name: str | None = None,
        context: Context | None = None,
    ) -> asyncio.Task[T]:
        return original_create_task(coro, name=name, context=context)

    sent = asyncio.Event()

    class Socket(fake_websocket_factory):
        @override
        async def send_text(self, payload: str) -> None:
            await super().send_text(payload)
            sent.set()

    manager = ConnectionManager()
    websocket = Socket()
    with monkeypatch.context() as patch:
        patch.setattr(loop, "create_task", create_task)
        try:
            await manager.connect(websocket)
            await manager.send_realtime_snapshot(websocket, FakeSnapshotBuilder())
            async with asyncio.timeout(1):
                await sent.wait()
            assert manager.active_connections == 1
            assert json.loads(websocket.sent_text[0])["event"] == "realtime.snapshot"
        finally:
            await manager.close()


@pytest.mark.parametrize("loop_name", ["asyncio", "auto"])
def test_connection_lifecycle_with_uvicorn_event_loop(
    fake_websocket_factory: type[FakeWebSocket], loop_name: str
) -> None:
    async def exercise() -> None:
        sent = asyncio.Event()

        class Socket(fake_websocket_factory):
            @override
            async def send_text(self, payload: str) -> None:
                await super().send_text(payload)
                sent.set()

        manager = ConnectionManager()
        websocket = Socket()
        try:
            await manager.connect(websocket)
            await manager.send_realtime_snapshot(websocket, FakeSnapshotBuilder())
            async with asyncio.timeout(1):
                await sent.wait()
            sent.clear()
            await manager.broadcast("schedules.changed", {"kind": "sync"})
            async with asyncio.timeout(1):
                await sent.wait()
            assert manager.active_connections == 1
            assert [json.loads(frame)["event"] for frame in websocket.sent_text] == [
                "realtime.snapshot",
                "schedules.changed",
            ]
        finally:
            await manager.close()
        assert manager.active_connections == 0
        assert websocket.closed is not None

    # Auto selects uvloop on Linux, matching the container's default command.
    config = Config("overture.main:create_app", factory=True, loop=loop_name)
    with asyncio.Runner(loop_factory=config.get_loop_factory()) as runner:
        runner.run(exercise())


async def test_slow_snapshot_drops_dead_connection_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    closed = asyncio.Event()

    class SlowWebSocket(fake_websocket_factory):
        @override
        async def send_text(self, payload: str) -> None:
            await asyncio.Event().wait()

        @override
        async def close(
            self, code: int | None = None, reason: str | None = None
        ) -> None:
            await super().close(code, reason)
            closed.set()

    manager = ConnectionManager(send_timeout=0.01)
    websocket = SlowWebSocket()
    await manager.connect(websocket)

    await asyncio.wait_for(
        manager.send_realtime_snapshot(websocket, FakeSnapshotBuilder()),
        timeout=1,
    )

    await asyncio.wait_for(closed.wait(), timeout=1)
    assert manager.active_connections == 0
    await manager.close()


async def test_broadcast_updates_projection_before_assigning_sequence(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    manager = ConnectionManager()
    websocket = fake_websocket_factory()
    projection_updates: list[tuple[int, str, object]] = []
    await manager.connect(websocket)

    def update_projection(event: str, data: dict[str, Any]) -> None:
        projection_updates.append((manager.sequence, event, data))

    await manager.broadcast(
        "schedules.changed",
        {"kind": "sync"},
        before_publish=update_projection,
    )

    assert projection_updates == [(0, "schedules.changed", {"kind": "sync"})]
    await asyncio.sleep(0)
    assert json.loads(websocket.sent_text[0])["sequence"] == 1


async def test_broadcast_fans_out_without_waiting_for_each_client(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    release_slow_client = asyncio.Event()
    fast_client_sent = asyncio.Event()

    class SlowWebSocket(fake_websocket_factory):
        @override
        async def send_text(self, payload: str) -> None:
            await release_slow_client.wait()
            await super().send_text(payload)

    class FastWebSocket(fake_websocket_factory):
        @override
        async def send_text(self, payload: str) -> None:
            await super().send_text(payload)
            fast_client_sent.set()

    manager = ConnectionManager()
    fast_websocket = FastWebSocket()
    slow_websocket = SlowWebSocket()
    await manager.connect(fast_websocket)
    await manager.connect(slow_websocket)

    broadcast = asyncio.create_task(
        manager.broadcast("schedules.changed", {"kind": "sync"})
    )
    await asyncio.wait_for(fast_client_sent.wait(), timeout=1)

    assert len(fast_websocket.sent_text) == 1
    assert broadcast.done() is True

    release_slow_client.set()
    await broadcast


class FakeSnapshotBuilder:
    """A snapshot builder that records when its slow phase ran."""

    def __init__(self) -> None:
        self.gathered = 0

    def capture(self) -> Mapping[str, Any]:
        return {}

    async def gather(self) -> Mapping[str, Any]:
        self.gathered += 1
        return {"jobs": []}

    def finish(
        self,
        captured: Mapping[str, Any],
        gathered: Mapping[str, Any],
        epoch: str,
        sequence: int,
    ) -> dict[str, JsonValue]:
        return {"epoch": epoch, "sequence": sequence, **captured, **gathered}


async def test_send_realtime_snapshot_uses_current_watermark(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    manager = ConnectionManager()
    websocket = fake_websocket_factory()
    await manager.connect(websocket)
    await manager.broadcast("schedules.changed", {"kind": "sync"})

    await manager.send_realtime_snapshot(websocket, FakeSnapshotBuilder())

    await asyncio.sleep(0)
    snapshot = json.loads(websocket.sent_text[-1])
    assert snapshot == {
        "epoch": manager.epoch,
        "sequence": 1,
        "event": "realtime.snapshot",
        "data": {"epoch": manager.epoch, "sequence": 1, "jobs": []},
    }


async def test_snapshot_does_not_cover_events_published_while_gathering(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    gathering = asyncio.Event()
    release = asyncio.Event()

    class PausedSnapshotBuilder(FakeSnapshotBuilder):
        @override
        async def gather(self) -> Mapping[str, Any]:
            gathering.set()
            await release.wait()
            return {"jobs": []}

    manager = ConnectionManager()
    websocket = fake_websocket_factory()
    await manager.connect(websocket)

    sending = asyncio.create_task(
        manager.send_realtime_snapshot(websocket, PausedSnapshotBuilder())
    )
    await gathering.wait()
    await manager.broadcast("schedules.changed", {"kind": "sync"})
    release.set()
    await sending

    event, snapshot = (json.loads(message) for message in websocket.sent_text)
    assert event["sequence"] == 1
    assert snapshot["sequence"] == 0
    assert snapshot["data"]["sequence"] == 0


async def test_client_resync_delegates_to_snapshot_builder(
    tmp_path: Path,
    fake_websocket_factory: type[FakeWebSocket],
    fake_media_provider: FakeMediaServerProvider,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    calls: list[tuple[ClientConnection, dict[str, JsonValue]]] = []

    class WebSockets(ConnectionManager):
        @override
        async def send_realtime_snapshot(
            self, websocket: ClientConnection, builder: SnapshotBuilder
        ) -> None:
            captured = builder.capture()
            gathered = await builder.gather()
            calls.append(
                (
                    websocket,
                    builder.finish(captured, gathered, "epoch-1", 7),
                )
            )

    websocket = fake_websocket_factory()
    runtime = make_runtime(
        config_dir=tmp_path,
        websockets=WebSockets(),
        provider_registry=NoopProviderRegistry(fake_media_provider),
        app_config=app_config,
        database=database,
    )

    before = utc_now()
    await resync.send_client_resync(websocket, runtime)
    after = utc_now()

    assert [connection for connection, _ in calls] == [websocket]
    snapshot = calls[0][1]
    assert snapshot["epoch"] == "epoch-1"
    assert snapshot["sequence"] == 7
    server_time = parse_utc_datetime(snapshot["server_time"])
    assert server_time is not None
    assert before <= server_time <= after


async def test_a_revoked_session_loses_only_its_own_sockets(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    manager = ConnectionManager()
    revoked, other_tab, someone_else = (fake_websocket_factory() for _ in range(3))
    await manager.connect(revoked, session_hash="revoked")
    await manager.connect(other_tab, session_hash="revoked")
    await manager.connect(someone_else, session_hash="kept")

    manager.revoke_session("revoked")
    await manager.broadcast("schedules.changed", {"kind": "sync"})
    await asyncio.sleep(0)

    assert manager.active_connections == 1
    assert [len(ws.sent_text) for ws in (revoked, other_tab, someone_else)] == [0, 0, 1]
    await manager.close()


async def test_a_built_event_is_sent_only_when_the_builder_produces_one(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    manager = ConnectionManager()
    websocket = fake_websocket_factory()
    await manager.connect(websocket)

    assert not await manager.broadcast_built(lambda: None)
    assert await manager.broadcast_built(
        lambda: ("schedules.changed", {"kind": "assets"})
    )
    await asyncio.sleep(0)

    [message] = [json.loads(text) for text in websocket.sent_text]
    assert (message["sequence"], message["data"]) == (1, {"kind": "assets"})
    await manager.close()


async def test_a_built_snapshot_carries_the_watermark_it_was_captured_at() -> None:
    manager = ConnectionManager()
    await manager.broadcast("schedules.changed", {"kind": "sync"})

    snapshot = await manager.build_snapshot(FakeSnapshotBuilder())

    assert snapshot == {"epoch": manager.epoch, "sequence": 1, "jobs": []}


class SignallingWebSocket(FakeWebSocket):
    """A socket that announces each frame it is sent."""

    def __init__(self) -> None:
        super().__init__()
        self.received = asyncio.Event()

    @override
    async def send_text(self, payload: str) -> None:
        await super().send_text(payload)
        self.received.set()


async def test_keepalives_reach_every_open_socket() -> None:
    manager = ConnectionManager(ping_interval=0)
    websocket = SignallingWebSocket()
    await manager.connect(websocket)

    pinging = asyncio.create_task(manager.start_ping_loop())
    async with asyncio.timeout(1):
        await websocket.received.wait()
    pinging.cancel()

    assert json.loads(websocket.sent_text[0]) == {"event": "ping"}
    await manager.close()


async def test_a_stopping_service_refuses_new_sockets(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    manager = ConnectionManager()
    await manager.close()

    with pytest.raises(RuntimeError, match="stopping"):
        await manager.connect(fake_websocket_factory())
