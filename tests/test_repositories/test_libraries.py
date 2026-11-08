"""The server's libraries as syncs record them, and what may be filed under them."""

lazy from datetime import UTC, datetime

lazy import pytest
lazy from sqlalchemy.exc import IntegrityError
lazy from sqlmodel import col, delete, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.library import Library
lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType
lazy from overture.media_servers.adapters import ServerSection
lazy from overture.repositories.libraries import LibraryRepository

_FIRST = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = datetime(2026, 2, 1, tzinfo=UTC)


async def _libraries(session: AsyncSession) -> list[tuple[str, str, str, bool]]:
    rows = (await session.exec(select(Library).order_by(col(Library.id)))).all()
    return [
        (row.id, row.media_type, row.title, row.removed_at is not None) for row in rows
    ]


async def test_a_sync_adds_renames_and_marks_libraries_removed(
    db_session: AsyncSession,
) -> None:
    await db_session.exec(delete(Library))
    repo = LibraryRepository(db_session)
    await repo.record(
        [
            ServerSection("a", "Films", MediaType.MOVIE),
            ServerSection("b", "Series", MediaType.SHOW),
        ],
        _FIRST,
    )
    await db_session.commit()

    # The next server lists "a" renamed, drops "b" and reuses its key for movies.
    await repo.record(
        [
            ServerSection("a", "Movies", MediaType.MOVIE),
            ServerSection("b", "More movies", MediaType.MOVIE),
        ],
        _LATER,
    )
    await db_session.commit()

    assert await _libraries(db_session) == [
        ("a", "movie", "Movies", False),
        ("b", "movie", "More movies", False),
        ("b", "show", "Series", True),
    ]
    assert [library.id for library in await repo.listed(["b"])] == ["b"]


async def test_an_item_is_filed_only_under_a_library_of_its_type(
    db_session: AsyncSession,
) -> None:
    await db_session.exec(delete(Library))
    await LibraryRepository(db_session).record(
        [ServerSection("films", "Films", MediaType.MOVIE)], _FIRST
    )
    await db_session.commit()
    db_session.add(
        MediaItem(media_type=MediaType.SHOW, title="Show", library_id="films")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
