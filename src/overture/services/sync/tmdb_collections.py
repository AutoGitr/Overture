"""Record which TMDB collection each movie belongs to."""

lazy import asyncio
lazy import logging
lazy from itertools import batched

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import Database
lazy from ...domain import MediaType
lazy from ...integrations.tmdb import TMDBClient
lazy from ...jobs.progress_log import JobOutcome, log_entry
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import SyncTally
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

    async def run(
        self, job: ManagedJob[SyncTally], *, library_ids: list[str] | None = None
    ) -> int:
        """Look up unchecked movies, reporting each bounded batch."""
        if not self._config.tmdb_configured or job.stop_requested():
            return 0
        async with self._database.read_session() as session:
            targets = await MediaItemRepository(
                session
            ).movies_without_tmdb_collection_check(library_ids)
        checked = 0

        async def lookup(tmdb_id: int) -> int | None:
            details = await self._tmdb.get_details(MediaType.MOVIE, tmdb_id)
            return details.collection_id if details else None

        for index, chunk in enumerate(batched(targets, _CONCURRENCY, strict=False)):
            if job.stop_requested():
                break
            await job.progress(
                log=log_entry(
                    JobOutcome.STARTED,
                    "Collections",
                    f"checking TMDB memberships {index * _CONCURRENCY + 1}"
                    f"-{index * _CONCURRENCY + len(chunk)} of {len(targets)}",
                )
            )
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
