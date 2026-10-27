"""Record what TMDB says about each title, for collection criteria and sets."""

lazy import asyncio
lazy import logging
lazy from datetime import timedelta
lazy from itertools import batched

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...integrations.tmdb import TMDBClient, TmdbFacts
lazy from ...jobs.progress_log import JobOutcome, log_entry
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import SyncTally
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...utils.errors import public_error_message
lazy from ...utils.time import utc_now

logger = logging.getLogger(__name__)

#: How many titles' details are fetched from TMDB at once.
_CONCURRENCY = 4
#: Ratings, streaming services and show status change, so facts are re-read.
REFRESH_AFTER = timedelta(days=7)


def record_tmdb_facts(item: MediaItem, facts: TmdbFacts | None) -> None:
    """Store a title's TMDB facts; ``None`` clears them for a title TMDB lacks."""
    item.original_language = facts.original_language if facts else None
    item.origin_countries = list(facts.origin_countries) if facts else []
    item.tmdb_rating = facts.rating if facts else None
    item.tmdb_votes = facts.votes if facts else None
    item.tmdb_keywords = list(facts.keywords) if facts else []
    item.companies = list(facts.companies) if facts else []
    item.networks = list(facts.networks) if facts else []
    item.streaming = list(facts.streaming) if facts else []
    item.show_status = facts.status if facts else None
    item.last_aired = facts.last_aired if facts else None
    # Jellyfin names a movie's collection itself; keep that when TMDB is silent.
    if facts is None or facts.collection_id is not None:
        item.tmdb_collection_id = facts.collection_id if facts else None


class TmdbEnrichment:
    """Look up each title's TMDB facts once per TMDB ID, and again weekly."""

    def __init__(
        self, *, app_config: Settings, database: Database, tmdb_client: TMDBClient
    ) -> None:
        self._config = app_config
        self._database = database
        self._tmdb = tmdb_client

    async def run(
        self, job: ManagedJob[SyncTally], *, library_ids: list[str] | None = None
    ) -> int:
        """Look up unchecked and outdated titles, reporting each bounded batch."""
        if not self._config.tmdb_configured or job.stop_requested():
            return 0
        async with self._database.read_session() as session:
            targets = await MediaItemRepository(session).titles_needing_tmdb_facts(
                utc_now() - REFRESH_AFTER, library_ids
            )
            region = (await get_app_settings(session)).tmdb_region
        checked = 0
        for index, chunk in enumerate(batched(targets, _CONCURRENCY, strict=False)):
            if job.stop_requested():
                break
            await job.progress(
                log=log_entry(
                    JobOutcome.STARTED,
                    "TMDB",
                    f"reading details {index * _CONCURRENCY + 1}"
                    f"-{index * _CONCURRENCY + len(chunk)} of {len(targets)}",
                )
            )
            results = await asyncio.gather(
                *(
                    self._tmdb.get_facts(media_type, tmdb_id, region)
                    for _, media_type, tmdb_id in chunk
                ),
                return_exceptions=True,
            )
            now = utc_now()
            async with self._database.write_session() as session:
                for (item_id, _, tmdb_id), result in zip(chunk, results, strict=True):
                    if isinstance(result, BaseException):
                        logger.debug(
                            "TMDB details of %s failed: %s",
                            tmdb_id,
                            public_error_message(result),
                        )
                        continue
                    item = await session.get(MediaItem, item_id)
                    # The title may have been rematched while TMDB answered.
                    if item is None or item.tmdb_id != tmdb_id:
                        continue
                    record_tmdb_facts(item, result)
                    item.tmdb_checked_id = tmdb_id
                    item.tmdb_checked_at = now
                    session.add(item)
                    checked += 1
        return checked
