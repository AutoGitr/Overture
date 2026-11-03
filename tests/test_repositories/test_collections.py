"""Numeric library collection links and membership integrity."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_collection import (
    MediaCollection,
    MediaCollectionMember,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType, ServerType
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.utils.time import utc_now


async def test_item_links_choose_the_matching_franchise(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        MediaItem(
            id=1, media_type=MediaType.MOVIE, title="Movie", tmdb_collection_id=10
        )
    )
    db_session.add_all(
        [
            MediaCollection(
                id=n,
                server_item_id=f"opaque-{n}",
                server_type=ServerType.JELLYFIN,
                media_type=MediaType.MOVIE,
                tmdb_collection_id=tmdb,
                last_synced_at=utc_now(),
            )
            for n, tmdb in [(1, None), (2, 10), (3, 99)]
        ]
    )
    await db_session.flush()
    db_session.add_all(
        MediaCollectionMember(collection_id=n, media_item_id=1) for n in [1, 2, 3]
    )
    await db_session.commit()
    assert await CollectionRepository(db_session).collection_ids_by_item([1]) == {
        1: [2]
    }
