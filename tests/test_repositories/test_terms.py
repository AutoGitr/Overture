"""Titles share term rows for their genres, people and other values."""

lazy import pytest
lazy from sqlmodel import col, delete, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.term import MediaItemTerm, Term
lazy from overture.domain import MediaType, TermKind
lazy from overture.repositories.collection_items import (
    CollectionItemRepository,
    TermSelection,
)
lazy from overture.repositories.terms import TermRepository
lazy from tests.media_servers import served_item


async def _terms(session: AsyncSession) -> int:
    return (await session.exec(select(func.count()).select_from(Term))).one()


async def test_titles_share_terms_and_keep_each_kinds_order(
    db_session: AsyncSession,
) -> None:
    repo = TermRepository(db_session)
    first = MediaItem(id=1, media_type=MediaType.MOVIE, title="First")
    second = MediaItem(id=2, media_type=MediaType.MOVIE, title="Second")
    db_session.add_all([first, second])
    await db_session.flush()
    assert await repo.assign(
        1,
        {
            TermKind.GENRE: ["Drama", "Action", "Drama", ""],
            TermKind.ACTOR: ["Lead"],
        },
    )
    assert await repo.assign(2, {TermKind.GENRE: ["Action"]})
    await db_session.commit()

    assert await _terms(db_session) == 3
    assert (await repo.values_of(1))[TermKind.GENRE] == ["Drama", "Action"]
    # Values of the same kind change nothing when they are already held.
    assert not await repo.assign(1, {TermKind.GENRE: ["Drama", "Action"]})
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
    await db_session.flush()
    await repo.assign(
        1, {TermKind.GENRE: ["Drama"], TermKind.LABEL: ["Kept", "Dropped"]}
    )
    await db_session.commit()

    await repo.assign(1, {TermKind.LABEL: ["New", "Kept"]})
    await db_session.commit()

    assert await repo.values_of(1) == {
        TermKind.GENRE: ["Drama"],
        TermKind.LABEL: ["New", "Kept"],
    }
    assert await repo.prune() == 1
    assert await _terms(db_session) == 3


async def test_one_name_is_a_separate_term_of_each_kind_and_is_reused(
    db_session: AsyncSession,
) -> None:
    repo = TermRepository(db_session)
    first = MediaItem(id=1, media_type=MediaType.MOVIE, title="First")
    second = MediaItem(id=2, media_type=MediaType.MOVIE, title="Second")
    db_session.add_all([first, second])
    await db_session.flush()
    names = {
        TermKind.GENRE: ["Action", "Comedy"],
        TermKind.ACTOR: ["Action", "Lead"],
    }
    assert await repo.assign(1, names)
    await db_session.commit()
    assert await _terms(db_session) == 4

    assert await repo.assign(2, names)
    await db_session.commit()
    assert await _terms(db_session) == 4
    assert await repo.values_of(2) == {
        TermKind.ACTOR: ["Action", "Lead"],
        TermKind.GENRE: ["Action", "Comedy"],
    }


async def _library_with_titles(session: AsyncSession) -> None:
    """Two titles of a library; each copy's labels are its server's own."""
    labels = {1: ["One", "Two"], 2: ["Two"]}
    for item_id, held in labels.items():
        item = served_item(
            id=item_id,
            media_type=MediaType.MOVIE,
            title=f"Title {item_id}",
            library_id="1:movies",
            server_item_id=str(item_id),
        )
        item.copies[0].labels = held
        session.add(item)
    await session.flush()
    repo = TermRepository(session)
    await repo.assign(
        1,
        {
            TermKind.ACTOR: ["Åsa Söderström", "Lead"],
            TermKind.GENRE: ["Drama"],
            TermKind.LABEL: ["One", "Two"],
        },
    )
    await repo.assign(2, {TermKind.ACTOR: ["Lead"], TermKind.LABEL: ["Two"]})


async def test_a_library_read_selects_values_and_unread_kinds_raise(
    db_session: AsyncSession,
) -> None:
    await _library_with_titles(db_session)

    first, second = await CollectionItemRepository(db_session).library_items(
        MediaType.MOVIE,
        "1:movies",
        TermSelection(
            kinds=frozenset({TermKind.LABEL}),
            matching={TermKind.ACTOR: frozenset({"åsa söderström"})},
        ),
    )

    assert list(first.values(TermKind.ACTOR)) == ["Åsa Söderström"]
    assert list(first.values(TermKind.LABEL)) == ["One", "Two"]
    assert list(second.values(TermKind.ACTOR)) == []
    assert list(second.values(TermKind.LABEL)) == ["Two"]
    with pytest.raises(KeyError):
        first.values(TermKind.GENRE)


async def test_term_counts_count_each_value_across_the_librarys_titles(
    db_session: AsyncSession,
) -> None:
    await _library_with_titles(db_session)

    assert await CollectionItemRepository(db_session).term_counts(
        MediaType.MOVIE, "1:movies", TermKind.ACTOR
    ) == {"Åsa Söderström": 1, "Lead": 2}
    # Labels are each server's own, as its copies hold them.
    assert await CollectionItemRepository(db_session).term_counts(
        MediaType.MOVIE, "1:movies", TermKind.LABEL
    ) == {"One": 1, "Two": 2}


async def test_assign_reports_only_the_kinds_that_changed(
    db_session: AsyncSession,
) -> None:
    await _library_with_titles(db_session)
    repo = TermRepository(db_session)

    assert await repo.assign(
        1,
        {
            TermKind.GENRE: ["Drama"],
            TermKind.ACTOR: ["Lead", "Åsa Söderström"],
        },
    ) == {TermKind.ACTOR}
    assert (await repo.values_of(1))[TermKind.ACTOR] == ["Lead", "Åsa Söderström"]


async def test_deleting_a_title_deletes_its_values_with_it(
    db_session: AsyncSession,
) -> None:
    await _library_with_titles(db_session)

    await db_session.exec(delete(MediaItem).where(col(MediaItem.id) == 1))

    assert (
        await db_session.exec(
            select(func.count())
            .select_from(MediaItemTerm)
            .where(col(MediaItemTerm.media_item_id) == 1)
        )
    ).one() == 0
