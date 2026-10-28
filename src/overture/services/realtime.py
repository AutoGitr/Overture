"""Build coherent process-local realtime snapshots."""

lazy from collections.abc import Mapping
lazy from dataclasses import dataclass
lazy from typing import Any, cast

lazy from ..jobs.slot import ManagedBackgroundJob
lazy from ..runtime import RuntimeServices
lazy from ..schemas.media_server import media_server_status
lazy from ..schemas.realtime import RealtimeJobSnapshot, RealtimeSnapshot
lazy from ..utils.security import sanitise_for_output
lazy from ..utils.time import utc_now_iso
lazy from ..utils.types import JsonValue


def _job_snapshot(job: ManagedBackgroundJob) -> RealtimeJobSnapshot | None:
    """Return the current running view or latest terminal view for one job slot."""
    event, payload = job.running_snapshot()
    if event is None:
        event, payload = job.final_snapshot()
    if not event or not payload:
        return None
    return RealtimeJobSnapshot(
        event=event,
        data=cast(
            "dict[str, JsonValue]",
            sanitise_for_output(payload),
        ),
    )


def _job_snapshots(runtime: RuntimeServices) -> list[RealtimeJobSnapshot]:
    """Return reconnect snapshots for all managed process-local job slots."""
    return [
        snapshot
        for job in runtime.job_slots.values()
        if (snapshot := _job_snapshot(job)) is not None
    ]


@dataclass(slots=True, frozen=True)
class RealtimeSnapshotBuilder:
    """Capture one realtime snapshot without holding the event lock over I/O.

    Reading the download queue and the dataset status are round trips; the
    job slots are process-local dictionaries. Capturing the latter with
    the watermark keeps later events replayable, while gathering the former
    outside the lock keeps jobs free to publish progress.
    """

    runtime: RuntimeServices

    def capture(self) -> Mapping[str, Any]:
        """Read process-local projections at the snapshot watermark."""
        return {
            "jobs": _job_snapshots(self.runtime),
            "media_server": media_server_status(
                self.runtime.provider_registry.health.current
            ),
        }

    async def gather(self) -> Mapping[str, Any]:
        """Read the parts of the snapshot that need I/O."""
        return {
            "downloads": await self.runtime.downloads.snapshot_events(),
            "public_dataset_status": await self.runtime.public_dataset.get_status(),
        }

    def finish(
        self,
        captured: Mapping[str, Any],
        gathered: Mapping[str, Any],
        epoch: str,
        sequence: int,
    ) -> dict[str, JsonValue]:
        """Return one validated snapshot at the connection manager watermark."""
        snapshot = RealtimeSnapshot(
            epoch=epoch,
            sequence=sequence,
            server_time=utc_now_iso(),
            **captured,
            **gathered,
        )
        return cast(
            "dict[str, JsonValue]",
            snapshot.model_dump(mode="json", exclude_none=True),
        )
