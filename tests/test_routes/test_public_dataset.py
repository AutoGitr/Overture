"""Public dataset router sync statuses."""

lazy from typing import override

lazy from overture.config import Settings
lazy from overture.routers import public_dataset
lazy from overture.schemas.common import Status
lazy from overture.schemas.public_dataset import PublicDatasetStatus
lazy from tests.runtime_helpers import (
    NoopPublicDataset,
)


async def test_public_dataset_sync_route_handles_disabled_started_and_running(
    app_config: Settings,
) -> None:
    class PublicDataset(NoopPublicDataset):
        enabled = False
        started = True

        @override
        async def get_status(self) -> PublicDatasetStatus:
            return self._noop_status(enabled=self.enabled)

        @override
        def start_background_sync(self) -> bool:
            return self.started

    service = PublicDataset(app_config=app_config)
    assert (
        await public_dataset.sync_public_dataset_now(service)
    ).status == Status.DISABLED

    service.enabled = True
    assert (
        await public_dataset.sync_public_dataset_now(service)
    ).status == Status.STARTED

    service.started = False
    assert (
        await public_dataset.sync_public_dataset_now(service)
    ).status == Status.ALREADY_RUNNING
