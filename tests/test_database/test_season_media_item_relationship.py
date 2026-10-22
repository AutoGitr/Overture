"""Season rows must be tied to their MediaItem by a real foreign key, and
deleting a MediaItem must delete its seasons - both through the ORM and at
the raw database level."""

lazy import pytest
lazy from sqlalchemy.exc import IntegrityError, InvalidRequestError
lazy from sqlmodel import select, text
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.domain import MediaType


async def _seed_item_with_seasons(session: AsyncSession) -> MediaItem:
    item = MediaItem(media_type=MediaType.SHOW, title="Show")
    session.add(item)
    await session.flush()
    assert item.id is not None
    item_id = item.id
    session.add_all(
        [
            Season(media_item_id=item_id, season_num=1, file_count=3),
            Season(media_item_id=item_id, season_num=2, file_count=5),
        ]
    )
    await session.flush()
    return item


async def test_season_foreign_key_rejects_orphaned_media_item_id(
    db_session: AsyncSession,
) -> None:
    """A season can't reference a media item that doesn't exist."""
    season = Season(media_item_id=999_999, season_num=1)
    db_session.add(season)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_media_item_via_orm_cascades_to_seasons(
    db_session: AsyncSession,
) -> None:
    item = await _seed_item_with_seasons(db_session)
    item_id = item.id

    await db_session.delete(item)
    await db_session.flush()

    remaining = (
        await db_session.exec(select(Season).where(Season.media_item_id == item_id))
    ).all()
    assert remaining == []


async def test_deleting_media_item_via_raw_sql_cascades_to_seasons(
    db_session: AsyncSession,
) -> None:
    """The database-level ON DELETE CASCADE backs up the ORM cascade for any
    deletion path that bypasses the SQLAlchemy session, e.g. a raw SQL
    statement or an external tool."""
    item = await _seed_item_with_seasons(db_session)
    item_id = item.id
    db_session.expunge_all()

    conn = await db_session.connection()
    await conn.execute(text("DELETE FROM media_items WHERE id = :id"), {"id": item_id})
    await db_session.flush()

    remaining = (
        await db_session.exec(select(Season).where(Season.media_item_id == item_id))
    ).all()
    assert remaining == []


async def test_unloaded_seasons_require_explicit_loading(
    db_session: AsyncSession,
) -> None:
    item = await _seed_item_with_seasons(db_session)
    item_id = item.id
    db_session.expunge_all()
    loaded = await db_session.get(MediaItem, item_id)
    assert loaded is not None
    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = loaded.seasons
    await db_session.refresh(loaded, attribute_names=["seasons"])
    assert {season.season_num for season in loaded.seasons} == {1, 2}
