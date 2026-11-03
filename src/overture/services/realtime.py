"""Build coherent process-local realtime snapshots."""

lazy from collections.abc import Collection, Mapping
lazy from dataclasses import dataclass
lazy from typing import Any, cast

lazy from ..jobs.slot import ManagedBackgroundJob
lazy from ..media_servers.registry import ProviderRegistry
lazy from ..schemas.media_server import media_server_status
lazy from ..schemas.realtime import RealtimeJobSnapshot, RealtimeSnapshot
lazy from ..utils.time import utc_now_iso
lazy from ..utils.types import JsonValue
lazy from .downloads import DownloadService
lazy from .public_dataset.service import PublicDatasetService


def _job_snapshot(job: ManagedBackgroundJob) -> RealtimeJobSnapshot | None:
    """Return the current running view or latest terminal view for one job slot."""
    event, payload = job.running_snapshot()
    if event is None:
        event, payload = job.final_snapshot()
    if not event or not payload:
        return None
    return RealtimeJobSnapshot(
        event=event,
        data=cast("dict[str, JsonValue]", payload),
    )


@dataclass(slots=True, frozen=True)
class RealtimeSnapshotBuilder:
    """Capture one realtime snapshot without holding the event lock over I/O.

    Reading the download queue and the dataset status are round trips; the
    job slots are process-local dictionaries. Capturing the latter with
    the watermark keeps later events replayable, while gathering the former
    outside the lock keeps jobs free to publish progress.
    """

    jobs: Collection[ManagedBackgroundJob]
    provider_registry: ProviderRegistry
    downloads: DownloadService
    public_dataset: PublicDatasetService

    def capture(self) -> Mapping[str, Any]:
        """Read process-local projections at the snapshot watermark."""
        return {
            "jobs": [
                snapshot
                for job in self.jobs
                if (snapshot := _job_snapshot(job)) is not None
            ],
            "media_server": media_server_status(self.provider_registry.health.current),
        }

    async def gather(self) -> Mapping[str, Any]:
        """Read the parts of the snapshot that need I/O."""
        return {
            "downloads": await self.downloads.snapshot_events(),
            "public_dataset_status": await self.public_dataset.get_status(),
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
