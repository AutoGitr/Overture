"""Sync router schedule delegation."""

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.routers import sync
lazy from overture.schemas.sync import SyncScheduleConfig, SyncScheduleWrite
lazy from tests.runtime_helpers import NoopSync, RecordingSchedules


async def test_sync_schedule_routes_delegate(
    *, app_config: Settings, database: Database
) -> None:
    engine = NoopSync(app_config=app_config)
    schedules = RecordingSchedules(app_config=app_config)
    engine.schedules = schedules
    body = SyncScheduleWrite(
        name="Poll",
        cron_expression="*/15 * * * *",
        config=SyncScheduleConfig(mode="incremental", library_ids=["movies"]),
    )

    assert await sync.list_sync_schedules(engine) == []
    await sync.create_sync_schedule(body, engine)
    await sync.update_sync_schedule(2, body, engine)
    assert (await sync.run_sync_schedule(2, engine)).status == "queued"
    assert (await sync.delete_sync_schedule(2, engine)).status == "deleted"

    assert schedules.calls == [
        ("list", None),
        ("create", ("Poll", body.config)),
        ("update", (2, "Poll", body.config)),
        ("run", 2),
        ("delete", 2),
    ]
