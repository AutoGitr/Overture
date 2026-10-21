"""Coverage for CollectionThemeRepository query and upsert helpers."""

lazy from datetime import UTC, datetime

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.domain import MediaType, ServerType
lazy from overture.repositories.collection_themes import CollectionThemeRepository

TS = datetime(2026, 1, 1, tzinfo=UTC)


async def test_bulk_monitor_upsert_preserves_themes_and_other_media_types(
    db_session: AsyncSession,
) -> None:
    repo = CollectionThemeRepository(db_session)
    await repo.upsert_uploaded_theme(
        server_item_id="existing",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="saved-theme",
        youtube_title="Saved theme",
        youtube_duration=60,
        server_theme_id="/themes/saved",
        timestamp=TS,
    )
    await repo.set_monitored(
        server_item_id="existing",
        media_type=MediaType.SHOW,
        server_type=ServerType.PLEX,
        monitored=True,
        timestamp=TS,
    )
    await db_session.commit()

    assert (
        await repo.bulk_set_monitored(
            ["existing", "new", "existing"],
            MediaType.MOVIE,
            False,
            server_type=ServerType.PLEX,
            timestamp=TS,
        )
        == 2
    )
    await db_session.commit()
    db_session.expire_all()

    existing = await repo.get_for_collection("existing", MediaType.MOVIE)
    created = await repo.get_for_collection("new", MediaType.MOVIE)
    show = await repo.get_for_collection("existing", MediaType.SHOW)
    assert existing is not None
    assert existing.monitored is False
    assert existing.youtube_id == "saved-theme"
    assert existing.server_theme_id == "/themes/saved"
    assert created is not None
    assert created.monitored is False
    assert show is not None
    assert show.monitored is True


async def test_get_for_collection_returns_none_when_absent(
    db_session: AsyncSession,
) -> None:
    repo = CollectionThemeRepository(db_session)

    assert await repo.get_for_collection("abc") is None


async def test_upsert_uploaded_theme_creates_new_row(db_session: AsyncSession) -> None:
    repo = CollectionThemeRepository(db_session)

    row = await repo.upsert_uploaded_theme(
        server_item_id="col-1",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="yt-123",
        youtube_title="Theme One",
        youtube_duration=90,
        server_theme_id="/themes/one",
        timestamp=TS,
    )
    await db_session.commit()

    assert row.id is not None
    assert row.youtube_id == "yt-123"
    assert row.youtube_title == "Theme One"
    assert row.youtube_duration == 90
    assert row.server_theme_id == "/themes/one"

    fetched = await repo.get_for_collection("col-1", MediaType.MOVIE)
    assert fetched is not None
    assert fetched.youtube_title == "Theme One"


async def test_upsert_uploaded_theme_updates_existing_row(
    db_session: AsyncSession,
) -> None:
    repo = CollectionThemeRepository(db_session)
    await repo.upsert_uploaded_theme(
        server_item_id="col-2",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="yt-old",
        youtube_title="Old Title",
        youtube_duration=80,
        server_theme_id="/themes/old",
        timestamp=TS,
    )
    await db_session.commit()

    updated = await repo.upsert_uploaded_theme(
        server_item_id="col-2",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="yt-new",
        youtube_title="New Title",
        youtube_duration=100,
        server_theme_id="/themes/new",
        timestamp=TS,
    )
    await db_session.commit()

    assert updated.youtube_title == "New Title"
    assert updated.youtube_id == "yt-new"

    fetched = await repo.get_for_collection("col-2", MediaType.MOVIE)
    assert fetched is not None
    assert fetched.youtube_title == "New Title"


async def test_clear_theme_noop_when_row_missing(db_session: AsyncSession) -> None:
    repo = CollectionThemeRepository(db_session)

    # Should not raise even though no matching row exists.
    await repo.clear_theme("missing", MediaType.MOVIE, timestamp=TS)


async def test_clear_theme_resets_existing_row(db_session: AsyncSession) -> None:
    repo = CollectionThemeRepository(db_session)
    await repo.upsert_uploaded_theme(
        server_item_id="col-4",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="yt-4",
        youtube_title="Has Theme",
        youtube_duration=60,
        server_theme_id="/themes/four",
        timestamp=TS,
    )
    await db_session.commit()

    await repo.clear_theme("col-4", MediaType.MOVIE, timestamp=TS)
    await db_session.commit()

    row = await repo.get_for_collection("col-4", MediaType.MOVIE)
    assert row is not None
    assert row.youtube_id is None
    assert row.youtube_title is None
    assert row.youtube_duration is None
    assert row.server_theme_id is None


async def test_set_monitored_creates_row_when_missing(db_session: AsyncSession) -> None:
    repo = CollectionThemeRepository(db_session)

    row = await repo.set_monitored(
        server_item_id="col-5",
        media_type=MediaType.MOVIE,
        server_type=ServerType.JELLYFIN,
        monitored=False,
        timestamp=TS,
    )
    await db_session.commit()

    assert row.monitored is False


async def test_emby_is_a_valid_persisted_server_type(db_session: AsyncSession) -> None:
    row = await CollectionThemeRepository(db_session).set_monitored(
        server_item_id="emby-col",
        media_type=MediaType.MOVIE,
        server_type=ServerType.EMBY,
        monitored=True,
        timestamp=TS,
    )
    await db_session.commit()

    assert row.server_type == "emby"


async def test_set_monitored_updates_existing_row(db_session: AsyncSession) -> None:
    repo = CollectionThemeRepository(db_session)
    await repo.upsert_uploaded_theme(
        server_item_id="col-6",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="yt-6",
        youtube_title="Existing",
        youtube_duration=60,
        server_theme_id="/themes/six",
        timestamp=TS,
    )
    await db_session.commit()

    updated = await repo.set_monitored(
        server_item_id="col-6",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        monitored=False,
        timestamp=TS,
    )
    await db_session.commit()

    assert updated.monitored is False
    assert updated.youtube_title == "Existing"
