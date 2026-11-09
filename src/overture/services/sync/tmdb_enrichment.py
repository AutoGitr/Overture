"""Record what TMDB says about each title, for collection criteria and sets."""

lazy import asyncio
lazy import logging
lazy from datetime import timedelta
lazy from itertools import batched

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import MediaType, TermKind
lazy from ...integrations.tmdb import TMDBClient, TmdbFacts
lazy from ...jobs.progress_log import JobOutcome, log_entry
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import SyncTally
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.terms import TermRepository
lazy from ...utils.security import sanitise_error
lazy from ...utils.time import utc_now

logger = logging.getLogger(__name__)

#: How many titles' details are fetched from TMDB at once.
_CONCURRENCY = 4
#: Ratings, streaming services and show status change, so facts are re-read.
REFRESH_AFTER = timedelta(days=7)


async def record_tmdb_facts(
    session: AsyncSession, item: MediaItem, facts: TmdbFacts | None
) -> None:
    """Store a title's TMDB facts; ``None`` clears them for a title TMDB lacks.

    The item is stored.
    """
    show = facts if item.media_type is MediaType.SHOW else None
    await TermRepository(session).assign(
        item.id or 0,
        {
            TermKind.ORIGIN_COUNTRY: facts.origin_countries if facts else (),
            TermKind.TMDB_KEYWORD: facts.keywords if facts else (),
            TermKind.COMPANY: facts.companies if facts else (),
            TermKind.STREAMING: facts.streaming if facts else (),
            TermKind.NETWORK: show.networks if show else (),
        },
    )
    item.original_language = facts.original_language if facts else None
    item.tmdb_rating = facts.rating if facts else None
    item.tmdb_votes = facts.votes if facts else None
    item.show_status = show.status if show else None
    item.last_aired = show.last_aired if show else None
    # Jellyfin names a movie's collection itself; keep that when TMDB is silent.
    if item.media_type is MediaType.MOVIE and (
        facts is None or facts.collection_id is not None
    ):
        item.tmdb_collection_id = facts.collection_id if facts else None
    # The media server's IDs win; TMDB fills those it does not name, which
    # lists, Radarr, Sonarr and OvertureDB match titles by.
    if facts is not None:
        item.imdb_id = item.imdb_id or facts.imdb_id
        item.tvdb_id = item.tvdb_id or facts.tvdb_id


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
                utc_now() - REFRESH_AFTER, library_ids=library_ids
            )
        return await self._read(targets, job)

    async def read_new(self, item_ids: list[int]) -> int:
        """Look up titles a poll just added, so criteria can test them at once."""
        if not self._config.tmdb_configured or not item_ids:
            return 0
        async with self._database.read_session() as session:
            targets = await MediaItemRepository(session).titles_needing_tmdb_facts(
                utc_now() - REFRESH_AFTER, item_ids=item_ids
            )
        return await self._read(targets, None)

    async def _read(
        self,
        targets: list[tuple[int, MediaType, int]],
        job: ManagedJob[SyncTally] | None,
    ) -> int:
        async with self._database.read_session() as session:
            region = (await get_app_settings(session)).tmdb_region
        checked = 0
        failures: list[str] = []
        for index, chunk in enumerate(batched(targets, _CONCURRENCY, strict=False)):
            if job is not None:
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
                        failures.append(sanitise_error(str(result)))
                        continue
                    item = await session.get(MediaItem, item_id)
                    # The title may have been rematched while TMDB answered.
                    if item is None or item.tmdb_id != tmdb_id:
                        continue
                    await record_tmdb_facts(session, item, result)
                    item.tmdb_checked_id = tmdb_id
                    item.tmdb_checked_at = now
                    session.add(item)
                    checked += 1
        if failures:
            # Unread titles keep no facts, so criteria cannot match them yet.
            message = (
                f"could not read {len(failures)} of {len(targets)} titles, which "
                f"the next sync tries again: {failures[0]}"
            )
            if job is None:
                logger.warning("TMDB %s", message)
            else:
                await job.report(JobOutcome.ERROR, "TMDB", message, finished=False)
        return checked
