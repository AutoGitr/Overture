"""Database-backed schedule helper coverage."""

lazy from datetime import UTC, datetime

lazy import pytest
lazy from pydantic import ValidationError
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.schemas.backup import BackupRetention
lazy from overture.schemas.public_dataset import PublicDatasetSyncStats
lazy from overture.services.schedule_store import (
    BACKUP_SCHEDULE,
    PUBLIC_DATASET_SCHEDULE,
    SYNC_SERVER_SCHEDULE,
    BackupPayload,
    PublicDatasetPayload,
    load_schedule,
    patch_payload,
    save_schedule,
)
lazy from overture.utils.cron import validate_cron_expression

SYNCED = datetime(2026, 1, 1, tzinfo=UTC)
PATCHED = datetime(2026, 2, 2, tzinfo=UTC)


async def test_loading_an_unsaved_schedule_returns_defaults_and_writes_no_row(
    db_session: AsyncSession,
) -> None:
    """Reading a schedule must never have a side effect on the database.

    A status endpoint or a scheduled run calls ``load_schedule`` far more
    often than anyone ever calls ``save_schedule``, so if reading wrote a row
    the first time, nearly every read anywhere in the app would silently open
    a write transaction. The declared defaults exist precisely so a read can
    answer without needing a row to exist yet; only ``save_schedule`` is
    allowed to create one.
    """
    server = await load_schedule(db_session, SYNC_SERVER_SCHEDULE)
    backup = await load_schedule(db_session, BACKUP_SCHEDULE)
    public = await load_schedule(db_session, PUBLIC_DATASET_SCHEDULE)

    assert server.payload.last_media_server is None
    assert server.enabled is False
    assert backup.payload.retention == BackupRetention()
    assert backup.enabled is True
    assert public.payload.last_status == "never_synced"
    assert public.enabled is False

    rows = (await db_session.exec(select(TaskSchedule))).all()
    assert rows == []


async def test_saving_a_schedule_round_trips_its_typed_payload(
    db_session: AsyncSession,
) -> None:
    saved = await save_schedule(
        db_session,
        PUBLIC_DATASET_SCHEDULE,
        enabled=True,
        payload=PublicDatasetPayload(
            last_synced_at=SYNCED,
            last_status="success",
            last_stats=PublicDatasetSyncStats(items=3),
        ),
    )

    assert saved.enabled is True
    assert saved.payload.last_synced_at == SYNCED
    assert saved.payload.last_status == "success"
    assert saved.payload.last_stats == PublicDatasetSyncStats(items=3)


async def test_patching_a_payload_leaves_the_other_fields_alone(
    db_session: AsyncSession,
) -> None:
    await save_schedule(
        db_session,
        PUBLIC_DATASET_SCHEDULE,
        payload=PublicDatasetPayload(
            last_status="success", last_stats=PublicDatasetSyncStats(items=3)
        ),
    )

    patched = await patch_payload(
        db_session,
        PUBLIC_DATASET_SCHEDULE,
        last_synced_at=PATCHED,
    )

    assert patched.payload.last_synced_at == PATCHED
    assert patched.payload.last_status == "success"
    assert patched.payload.last_stats == PublicDatasetSyncStats(items=3)


async def test_patching_rejects_unknown_fields_and_invalid_values(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="Unknown schedule payload fields"):
        await patch_payload(db_session, PUBLIC_DATASET_SCHEDULE, app_config=None)
    with pytest.raises(ValidationError):
        await patch_payload(db_session, PUBLIC_DATASET_SCHEDULE, last_status="ok")


async def test_out_of_range_payload_values_are_rejected_not_clamped() -> None:
    """The declared range is the contract; silent clamping hides mistakes."""
    with pytest.raises(ValidationError):
        BackupPayload.model_validate({"retention": {"daily": -1}})


def test_cron_validation_rejects_empty_and_invalid_values() -> None:
    for value in ("", "not cron", "* * *"):
        with pytest.raises(ValueError, match=r"cron_expression"):
            validate_cron_expression(value)
