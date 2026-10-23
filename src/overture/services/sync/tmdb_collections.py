"""Record which TMDB collection each movie belongs to."""

lazy import asyncio
lazy import logging
lazy from itertools import batched

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import MediaType
lazy from ...integrations.tmdb import TMDBClient
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...utils.errors import public_error_message

logger = logging.getLogger(__name__)

#: How many movies' details are fetched from TMDB at once.
_CONCURRENCY = 4


class TmdbCollectionEnrichment:
    """Look each movie's TMDB collection up once per TMDB ID.

    Movies a server already names a collection for (Jellyfin) are skipped,
    so TMDB is asked only for what nothing else says.
    """

    def __init__(
        self, *, app_config: Settings, database: Database, tmdb_client: TMDBClient
    ) -> None:
        self._config = app_config
        self._database = database
        self._tmdb = tmdb_client

    async def run(self) -> int:
        """Look up every movie not yet checked; return how many were checked."""
        if not self._config.tmdb_configured:
            return 0
        async with self._database.read_session() as session:
            targets = await MediaItemRepository(
                session
            ).movies_without_tmdb_collection_check()
        checked = 0
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def lookup(tmdb_id: int) -> int | None:
            async with semaphore:
                details = await self._tmdb.get_details(MediaType.MOVIE, tmdb_id)
            return details.collection_id if details else None

        for chunk in batched(targets, CHUNK_SIZE, strict=False):
            results = await asyncio.gather(
                *(lookup(tmdb_id) for _, tmdb_id in chunk), return_exceptions=True
            )
            async with self._database.write_session() as session:
                for (item_id, tmdb_id), result in zip(chunk, results, strict=True):
                    if isinstance(result, BaseException):
                        logger.debug(
                            "TMDB collection of movie %s failed: %s",
                            tmdb_id,
                            public_error_message(result),
                        )
                        continue
                    item = await session.get(MediaItem, item_id)
                    # The movie may have been rematched while TMDB answered.
                    if item is None or item.tmdb_id != tmdb_id:
                        continue
                    item.tmdb_collection_id = result
                    item.tmdb_collection_checked_id = tmdb_id
                    session.add(item)
                    checked += 1
        return checked
