"""Titles share term rows for their genres, people and other values."""

lazy from sqlmodel import func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.term import Term
lazy from overture.domain import MediaType, TermKind
lazy from overture.repositories.media_items import WITH_TERMS
lazy from overture.repositories.terms import TermRepository


async def _terms(session: AsyncSession) -> int:
    return (await session.exec(select(func.count()).select_from(Term))).one()


async def test_titles_share_terms_and_keep_each_kinds_order(
    db_session: AsyncSession,
) -> None:
    repo = TermRepository(db_session)
    first = MediaItem(id=1, media_type=MediaType.MOVIE, title="First")
    second = MediaItem(id=2, media_type=MediaType.MOVIE, title="Second")
    db_session.add_all([first, second])
    assert await repo.assign(
        first,
        {
            TermKind.GENRE: ["Drama", "Action", "Drama", ""],
            TermKind.ACTOR: ["Lead"],
        },
    )
    assert await repo.assign(second, {TermKind.GENRE: ["Action"]})
    await db_session.commit()

    assert await _terms(db_session) == 3
    assert first.values(TermKind.GENRE) == ["Drama", "Action"]
    # Values of the same kind change nothing when they are already held.
    assert not await repo.assign(first, {TermKind.GENRE: ["Drama", "Action"]})
    assert await repo.values_by_item([1, 2], TermKind.GENRE) == {
        1: ["Drama", "Action"],
        2: ["Action"],
    }
    assert await repo.values_of(1) == {
        TermKind.GENRE: ["Drama", "Action"],
        TermKind.ACTOR: ["Lead"],
    }


async def test_reassigning_keeps_other_kinds_and_prune_drops_unheld_terms(
    db_session: AsyncSession,
) -> None:
    repo = TermRepository(db_session)
    item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie")
    db_session.add(item)
    await repo.assign(
        item, {TermKind.GENRE: ["Drama"], TermKind.LABEL: ["Kept", "Dropped"]}
    )
    await db_session.commit()

    loaded = await db_session.get(MediaItem, 1, options=[WITH_TERMS])
    assert loaded is not None
    await repo.assign(loaded, {TermKind.LABEL: ["New", "Kept"]})
    await db_session.commit()

    assert loaded.values(TermKind.GENRE) == ["Drama"]
    assert loaded.values(TermKind.LABEL) == ["New", "Kept"]
    assert await repo.prune() == 1
    assert await _terms(db_session) == 3


async def test_one_name_is_a_separate_term_of_each_kind_and_is_reused(
    db_session: AsyncSession,
) -> None:
    repo = TermRepository(db_session)
    first = MediaItem(id=1, media_type=MediaType.MOVIE, title="First")
    second = MediaItem(id=2, media_type=MediaType.MOVIE, title="Second")
    db_session.add_all([first, second])
    names = {
        TermKind.GENRE: ["Action", "Comedy"],
        TermKind.ACTOR: ["Action", "Lead"],
    }
    assert await repo.assign(first, names)
    await db_session.commit()
    assert await _terms(db_session) == 4

    assert await repo.assign(second, names)
    await db_session.commit()
    assert await _terms(db_session) == 4
    assert second.values(TermKind.GENRE) == ["Action", "Comedy"]
    assert second.values(TermKind.ACTOR) == ["Action", "Lead"]
