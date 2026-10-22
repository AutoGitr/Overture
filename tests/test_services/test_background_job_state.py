"""Managed job lifecycle and snapshot ownership."""

lazy import asyncio
lazy from collections.abc import Callable
lazy from typing import Any, override

lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.ws.state import BackgroundJobRegistry
lazy from tests.publishers import NullEventPublisher

SCAN_LIFECYCLE = ManagedJobLifecycle(JobKind.ASSET_SCAN)


class RecordingPublisher(NullEventPublisher):
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    @override
    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: Callable[[str, Any], None] | None = None,
    ) -> None:
        if before_publish is not None:
            before_publish(event, payload)
        self.events.append((event, payload))


class TestBackgroundJobState:
    def test_terminal_snapshots_clear_and_patch_only_when_tokens_match(self) -> None:
        slot = ManagedBackgroundJob(SCAN_LIFECYCLE, NullEventPublisher())
        slot.save_snapshot(
            "assets.scan.completed",
            {"finished_at": "finish-1", "issues": [{"renamed": False}]},
        )

        assert slot.clear_final_snapshot("stale") == "stale"
        assert slot.patch_final_snapshot(
            "finish-1",
            lambda payload: {**payload, "issues": [{"renamed": True}]},
        ) == (
            "assets.scan.completed",
            {"finished_at": "finish-1", "issues": [{"renamed": True}]},
        )
        assert slot.clear_final_snapshot("finish-1") == "cleared"
        assert slot.clear_final_snapshot("finish-1") == "empty"

    async def test_slot_tracks_running_state_stop_requests_and_snapshots(self) -> None:
        slot = ManagedBackgroundJob(SCAN_LIFECYCLE, NullEventPublisher())
        event = asyncio.Event()

        async def job():
            await event.wait()

        assert slot.start_with_context(lambda _: job()) is True
        assert slot.start_with_context(lambda _: job()) is False
        assert slot.running is True

        slot.request_stop()
        slot.save_snapshot("job.completed", {"ok": True})
        assert slot.stop_requested is True
        assert slot.last_event == "job.completed"
        assert slot.last_payload == {"ok": True}

        event.set()
        await slot.wait_idle()
        assert slot.running is False

    async def test_cancelled_task_is_cleared_without_raising(self) -> None:
        slot = ManagedBackgroundJob(SCAN_LIFECYCLE, NullEventPublisher())

        async def job():
            await asyncio.Event().wait()

        assert slot.start_with_context(lambda _: job()) is True
        task = slot.task
        assert task is not None
        task.cancel()
        await slot.wait_idle()

        assert slot.running is False
        assert slot.task is None

    async def test_registry_stop_drains_active_jobs_and_terminal_events(self) -> None:
        publisher = RecordingPublisher()
        registry = BackgroundJobRegistry(publisher)

        async def job() -> None:
            await asyncio.Event().wait()

        assert registry.art_match.start_with_context(lambda _: job()) is True
        await asyncio.sleep(0)
        await registry.stop()

        assert registry.art_match.running is False
        assert registry.art_match.task is None
        assert publisher.events[0][0] == "match.stopped"

    async def test_slot_context_publishes_standard_lifecycle_payload(
        self,
    ) -> None:
        publisher = RecordingPublisher()
        slot = ManagedBackgroundJob(
            ManagedJobLifecycle(
                JobKind.SYNC,
                event_job_id="sync:manual",
                target={"library_ids": ["1"]},
            ),
            publisher=publisher,
        )

        async def job(context: JobContext) -> None:
            await context.publish_lifecycle(
                "progress",
                done=1,
                checked=1,
                pulled=1,
            )

        assert slot.start_with_context(job) is True
        await slot.wait_idle()
        assert publisher.events[-1][0] == "sync.completed"
        assert publisher.events[:-1] == [
            (
                "sync.progress",
                {
                    "done": 1,
                    "checked": 1,
                    "pulled": 1,
                    "started_at": slot.started_at,
                    "job": {
                        "kind": "sync",
                        "status": "progress",
                        "id": "sync:manual",
                        "target": {"library_ids": ["1"]},
                    },
                },
            )
        ]

    def test_registry_keeps_terminal_snapshots_independent(self) -> None:
        registry = BackgroundJobRegistry(NullEventPublisher())
        registry.asset_scan.save_snapshot("assets.scan.completed", {"issues": []})
        assert registry.asset_scan.last_payload == {"issues": []}
        assert all(
            slot.last_payload is None
            for slot in registry.values()
            if slot is not registry.asset_scan
        )
