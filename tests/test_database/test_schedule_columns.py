"""Native JSON values and closed-vocabulary schedule columns."""

lazy from datetime import UTC, datetime
lazy from typing import cast

lazy import pytest

lazy from overture.db.models.saved_schedule import SavedSchedule
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.domain import ScheduleKind


def test_task_schedule_payload_is_native_dict() -> None:
    schedule = TaskSchedule(task_name="sync", payload={"library_ids": ["1"]})
    assert schedule.payload == {"library_ids": ["1"]}

    schedule.payload = {}
    assert schedule.payload == {}


def test_bulk_schedule_payload_is_native_dict() -> None:
    schedule = SavedSchedule(
        kind=ScheduleKind.ASSETS,
        name="Nightly",
        cron_expression="0 3 * * *",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"library_ids": ["1"]},
    )
    assert schedule.payload == {"library_ids": ["1"]}

    schedule.payload = {}
    assert schedule.payload == {}


def test_constructing_a_row_with_an_unknown_enum_value_fails_immediately() -> None:
    """A typo in a closed-vocabulary column must not reach the database."""
    with pytest.raises(ValueError, match="not a valid ScheduleKind"):
        SavedSchedule(
            kind=cast("ScheduleKind", "unsupported"),
            name="Nightly",
            cron_expression="0 3 * * *",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
