"""Public dataset and schedule helper coverage."""

lazy import asyncio
lazy from contextlib import asynccontextmanager
lazy from datetime import UTC, datetime
lazy from pathlib import Path

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy import overture.services.public_dataset.service as service_module
lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType
lazy from overture.schemas.art import ArtCandidate
lazy from overture.schemas.public_dataset import PublicDatasetSyncStats
lazy from overture.services.public_dataset.catalog import (
    PUBLIC_DATASET_REPO_URL,
    catalog_url_candidates,
    get_public_dataset_catalog_url,
)
lazy from overture.services.public_dataset.lookup import (
    build_candidate,
)
lazy from overture.services.public_dataset.service import PublicDatasetService
lazy from overture.services.schedule_store import (
    BackupPayload,
    PublicDatasetPayload,
    Schedule,
    ScheduleSpec,
    SyncServerPayload,
)
lazy from overture.services.scheduler import ScheduledJobInfo, SchedulerService
lazy from overture.utils.cron import validate_cron_expression
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import database_for


class TestPublicDatasetHelper:
    async def test_set_enabled_returns_scheduler_next_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        app_config: Settings,
    ) -> None:
        class _Session:
            def in_transaction(self) -> bool:
                return False

            async def commit(self) -> None:
                pass

            async def rollback(self) -> None:
                pass

        @asynccontextmanager
        async def session_factory():
            yield _Session()

        async def fake_save(
            _session: AsyncSession,
            _spec: ScheduleSpec[PublicDatasetPayload],
            *,
            enabled: bool,
            **_kwargs: object,
        ) -> Schedule[PublicDatasetPayload]:
            return Schedule(
                enabled=enabled,
                cron_expression="0 3 * * *",
                payload=PublicDatasetPayload(),
                updated_at=None,
                timezone=app_config.TZ,
            )

        database = database_for(session_factory)
        service = PublicDatasetService(
            scheduler=SchedulerService(app_config=app_config),
            publisher=NullEventPublisher(),
            app_config=app_config,
            database=database,
            config_dir=tmp_path,
        )
        monkeypatch.setattr(service_module, "save_schedule", fake_save)

        def fake_schedule_job(_schedule: object) -> None:
            return None

        monkeypatch.setattr(service, "_schedule_job", fake_schedule_job)

        def job_info(_job_id: str) -> ScheduledJobInfo:
            return ScheduledJobInfo(enabled=True, next_run="2026-06-01T03:00:00+00:00")

        monkeypatch.setattr(service.scheduler, "job_info", job_info)

        status = await service.set_enabled(True)

        assert status.next_run == "2026-06-01T03:00:00+00:00"

    def test_catalog_url_is_derived_from_github_repo(self) -> None:
        assert (
            get_public_dataset_catalog_url()
            == "https://AutoGitr.github.io/OvertureDB/catalog.jsonl.gz"
        )
        assert catalog_url_candidates() == [
            "https://AutoGitr.github.io/OvertureDB/catalog.jsonl.gz",
            "https://AutoGitr.github.io/OvertureDB/catalog.jsonl",
        ]

    def test_candidate_shape_and_status_projection(
        self, tmp_path: Path, *, app_config: Settings, database: Database
    ) -> None:
        assert build_candidate(None, ArtType.POSTER) is None
        assert build_candidate(
            "https://theposterdb.com/api/assets/1", ArtType.POSTER
        ) == ArtCandidate(
            url="https://theposterdb.com/api/assets/1",
            source="tpdb",
            title="OvertureDB",
            art_type=ArtType.POSTER,
        )

        service = PublicDatasetService(
            scheduler=SchedulerService(app_config=app_config),
            publisher=NullEventPublisher(),
            app_config=app_config,
            database=database,
            config_dir=tmp_path,
        )
        try:
            status = service.status_from_schedule(
                Schedule(
                    enabled=True,
                    cron_expression="0 0 * * *",
                    payload=PublicDatasetPayload(
                        last_synced_at=datetime(2026, 1, 1, tzinfo=UTC),
                        last_status="success",
                        last_stats=PublicDatasetSyncStats(items=4),
                    ),
                    updated_at=None,
                    timezone=app_config.TZ,
                )
            )
        finally:
            asyncio.run(service.stop())

        assert status.enabled is True
        assert status.repo_url == PUBLIC_DATASET_REPO_URL
        assert status.catalog_url == get_public_dataset_catalog_url()
        assert status.last_stats == PublicDatasetSyncStats(items=4)


class TestScheduleHelper:
    def test_validate_cron_expression_normalises_whitespace(self) -> None:
        assert validate_cron_expression("  0   3  *  *  *  ") == "0 3 * * *"

    def test_validate_cron_expression_rejects_invalid_or_empty_values(self) -> None:
        for expression in ("", "not cron", "* * *", "* * * * * *"):
            with pytest.raises(ValueError, match=r"cron_expression"):
                validate_cron_expression(expression)

    def test_payload_models_fill_in_defaults_for_missing_keys(self) -> None:
        """A stored payload only has to carry the fields it actually set."""
        assert SyncServerPayload.model_validate({}).model_dump() == {
            "last_media_server": None,
        }
        assert BackupPayload.model_validate(
            {"retention": {"latest": 5}}
        ).model_dump() == {
            "retention": {"latest": 5, "daily": 7, "weekly": 4, "monthly": 6},
        }
        assert PublicDatasetPayload().model_dump() == {
            "last_synced_at": None,
            "last_status": "never_synced",
            "last_stats": None,
        }

    def test_payload_models_reject_out_of_range_values(self) -> None:
        """Ranges are declared once on the payload rather than clamped ad hoc."""
        with pytest.raises(ValueError, match="latest"):
            BackupPayload.model_validate({"retention": {"latest": 0}})
