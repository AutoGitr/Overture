"""Bulk library operations commit and publish whole sets of items."""

lazy from pathlib import Path

lazy import pytest
lazy from sqlalchemy import event
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.ledger import read_asset, select_art
lazy from overture.db.models.asset import Asset
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import CHUNK_SIZE, Database
lazy from overture.domain import ArtType, MediaType, ServerAsset
lazy from overture.schemas.library import BulkItemOperation
lazy from overture.utils.art_urls import PublicArtUrl
lazy from tests.factories import (
    local_hash,
    seed_asset,
    seed_theme,
    theme_file_hash,
    theme_of,
)
lazy from tests.runtime_helpers import RecordingPublisher, make_runtime


@pytest.mark.parametrize(
    "operation", ["artwork", "themes", "delete", "monitor", "unmonitor"]
)
async def test_bulk_operation_preserves_untargeted_records(
    tmp_path: Path, database: Database, app_config: Settings, operation: str
) -> None:
    events = RecordingPublisher()
    runtime = make_runtime(
        config_dir=tmp_path, database=database, app_config=app_config, events=events
    )
    async with database.write_session() as session:
        for item_id in (1, 2, 3):
            item = seed_theme(
                MediaItem(
                    id=item_id,
                    title=f"Show {item_id}",
                    media_type=MediaType.SHOW,
                    monitored=operation != "monitor",
                ),
                "saved-theme",
                title="Theme",
                duration=60,
                file_hash="local-hash",
            )
            select_art(item, ServerAsset.POSTER, PublicArtUrl("poster"))
            seed_asset(item, ArtType.POSTER, file_hash="poster-hash")
            season = Season(id=item_id, media_item_id=item_id, season_num=1)
            select_art(season, ServerAsset.SEASON_POSTER, PublicArtUrl("season"))
            session.add(item)
            await session.flush()
            session.add(season)

    result = await runtime.library.bulk_operate_items(
        BulkItemOperation.model_validate(
            {"item_ids": [1, 2, 1, 999], "operation": operation}
        )
    )
    assert set(result.item_ids) == {1, 2}
    if operation in {"artwork", "themes"}:
        # Each removal is the one a single item's takes, with its own event.
        assert [event for event, _ in events.events] == ["library.item.upserted"] * 2
        assert set(result.errors) == {999}
    else:
        assert events.events == [
            ("library.items.changed", result.model_dump(mode="json"))
        ]

    async with database.read_session() as session:
        items = {
            item.id: item for item in (await session.exec(select(MediaItem))).all()
        }
        seasons = (await session.exec(select(Season))).all()
        slots = (await session.exec(select(Asset))).unique().all()
        assert theme_of(items[3]).youtube_id == "saved-theme"
        assert read_asset(items[3], ServerAsset.POSTER).url == "poster"
        assert items[3].monitored is (operation != "monitor")
        if operation == "delete":
            assert set(items) == {3}
            assert [season.media_item_id for season in seasons] == [3]
            assert len(slots) == 3
        else:
            for item_id in (1, 2):
                item = items[item_id]
                assert theme_file_hash(item) == "local-hash"
                if operation == "themes":
                    assert theme_of(item).youtube_id is None
                    assert theme_of(item).youtube_title is None
                    assert theme_of(item).youtube_duration is None
                    assert theme_of(item).provenance_cleared is True
                elif operation == "artwork":
                    # The selection is forgotten; the local file record stays.
                    poster = read_asset(item, ServerAsset.POSTER)
                    assert poster.url is None
                    assert local_hash(item, ServerAsset.POSTER) == "poster-hash"
                    assert len(slots) == 9
                else:
                    assert item.monitored is (operation == "monitor")


@pytest.mark.parametrize("fail_second_batch", [False, True])
async def test_large_bulk_operation_batches_sql_and_rolls_back_as_one_transaction(
    tmp_path: Path, database: Database, app_config: Settings, *, fail_second_batch: bool
) -> None:
    events = RecordingPublisher()
    runtime = make_runtime(
        config_dir=tmp_path, database=database, app_config=app_config, events=events
    )
    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(id=item_id, title="Movie", media_type=MediaType.MOVIE)
                for item_id in range(1, CHUNK_SIZE + 2)
            ]
        )

    updates: list[str] = []

    def track_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.startswith("UPDATE media_items"):
            updates.append(statement)
            if fail_second_batch and len(updates) == 2:
                raise RuntimeError("Second batch failed")

    event.listen(database.engine.sync_engine, "before_cursor_execute", track_statement)
    try:
        body = BulkItemOperation(
            item_ids=list(range(1, CHUNK_SIZE + 2)), operation="unmonitor"
        )
        if fail_second_batch:
            with pytest.raises(RuntimeError, match="Second batch failed"):
                await runtime.library.bulk_operate_items(body)
        else:
            result = await runtime.library.bulk_operate_items(body)
            assert len(result.item_ids) == CHUNK_SIZE + 1
    finally:
        event.remove(
            database.engine.sync_engine, "before_cursor_execute", track_statement
        )

    assert len(updates) == 2
    assert len(events.events) == (0 if fail_second_batch else 1)
    async with database.read_session() as session:
        assert all(
            item.monitored is fail_second_batch
            for item in (await session.exec(select(MediaItem))).all()
        )
