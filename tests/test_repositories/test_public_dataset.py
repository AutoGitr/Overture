"""Coverage for resolving local media items to their OvertureDB rows."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.domain import MediaType
lazy from overture.repositories.public_dataset import PublicDatasetRepository
lazy from tests.factories import MediaItemFactory, PublicDatasetItemFactory
lazy from tests.runtime_helpers import row_id


async def test_lookup_prefers_tmdb_for_shows_and_movies(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
) -> None:
    """Shows and movies alike are identified by TMDB first, then TVDB."""
    show = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        title="Show",
        server_item_id="show",
        tmdb_id=100,
        tvdb_id=200,
    )
    movie = media_item_factory(
        id=None,
        title="Movie",
        server_item_id="movie",
        tmdb_id=300,
        tvdb_id=400,
    )
    db_session.add_all([show, movie])
    db_session.add_all(
        [
            public_dataset_item_factory(
                id=None, media_type=MediaType.SHOW, tmdb_id=100, title="by tmdb"
            ),
            public_dataset_item_factory(
                id=None, media_type=MediaType.SHOW, tvdb_id=200, title="by tvdb"
            ),
            public_dataset_item_factory(id=None, tmdb_id=300, title="by tmdb"),
            public_dataset_item_factory(id=None, tvdb_id=400, title="by tvdb"),
        ]
    )
    await db_session.commit()

    matched = await PublicDatasetRepository(db_session).items_by_media_item_id(
        [show, movie]
    )

    assert matched[row_id(show)].title == "by tmdb"
    assert matched[row_id(movie)].title == "by tmdb"


async def test_items_without_a_dataset_row_are_absent_from_the_result(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=None, server_item_id="unknown", tmdb_id=999)
    db_session.add(item)
    await db_session.commit()

    matched = await PublicDatasetRepository(db_session).items_by_media_item_id([item])

    assert matched == {}


async def test_an_id_of_one_media_type_never_matches_the_other(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
) -> None:
    movie = media_item_factory(id=None, server_item_id="movie", tmdb_id=42)
    db_session.add(movie)
    db_session.add(
        public_dataset_item_factory(id=None, media_type=MediaType.SHOW, tmdb_id=42)
    )
    await db_session.commit()

    matched = await PublicDatasetRepository(db_session).items_by_media_item_id([movie])

    assert matched == {}
