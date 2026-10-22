"""Backup schedule input validation."""

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.schemas.backup import BackupScheduleUpdate


def test_retention_requires_at_least_one_latest_backup() -> None:
    with pytest.raises(ValidationError):
        BackupScheduleUpdate.model_validate({"retention": {"latest": 0}})


@pytest.mark.parametrize("cron", ["", "not cron"])
def test_schedule_requires_a_valid_cron(cron: str) -> None:
    with pytest.raises(ValidationError):
        BackupScheduleUpdate(cron_expression=cron)
