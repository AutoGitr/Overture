"""Refresh seasons for saved TMDB shows that have no media-server item."""

lazy import asyncio
lazy import logging

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import MediaType
lazy from ...integrations.tmdb import TMDBClient
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import SyncTally
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.errors import public_error_message
lazy from ...utils.time import utc_now
lazy from ..library.items import emit_library_item_upserted

logger = logging.getLogger(__name__)

#: How many shows' seasons are fetched from TMDB at once.
_CONCURRENCY = 4


class TmdbSeasonSync:
    """Add newly listed seasons without replacing saved asset selections."""

    def __init__(
        self,
        *,
        app_config: Settings,
        database: Database,
        tmdb_client: TMDBClient,
        publisher: protocols.EventPublisher,
    ) -> None:
        self._config = app_config
        self._database = database
        self._tmdb = tmdb_client
        self._publisher = publisher

    async def targets(self) -> list[MediaItem]:
        """Plan only visible, unconnected shows while TMDB is configured."""
        if not self._config.tmdb_configured:
            return []
        async with self._database.read_session() as session:
            return await MediaItemRepository(session).list_unconnected_tmdb_shows()

    async def run(self, items: list[MediaItem], job: ManagedJob[SyncTally]) -> None:
        """Refresh one show per transaction and report each planned outcome.

        A few shows are fetched at once; TMDB's own rate limit paces them.
        """
        pending = iter(items)

        async def refresh_pending() -> None:
            for item in pending:
                if job.stop_requested():
                    return
                try:
                    outcome, reason = await self._refresh(item)
                except Exception as exc:
                    logger.debug("TMDB seasons for %s failed", item.title, exc_info=exc)
                    outcome, reason = JobOutcome.ERROR, public_error_message(exc)
                await job.report(outcome, item.title, reason)

        async with asyncio.TaskGroup() as group:
            for _ in range(min(_CONCURRENCY, len(items))):
                group.create_task(refresh_pending())

    async def _refresh(self, expected: MediaItem) -> tuple[JobOutcome, str]:
        """Fetch outside the write session, then recheck that the show is unlinked."""
        if expected.id is None or expected.tmdb_id is None:
            raise ValueError("TMDB season sync requires a saved show with a TMDB ID")
        async with self._database.read_session() as session:
            current = await session.get(MediaItem, expected.id)
            if not self._matches(current, expected):
                return JobOutcome.SKIPPED, "show is no longer an unconnected TMDB item"
        details = await self._tmdb.get_details(MediaType.SHOW, expected.tmdb_id)
        if details is None:
            raise ValueError("Show was not found on TMDB")
        changed = False
        async with self._database.write_session() as session:
            current = await session.get(MediaItem, expected.id)
            if current is None or not self._matches(current, expected):
                return JobOutcome.SKIPPED, "show changed while reading TMDB"
            seasons = await SeasonRepository(session).map_by_number_for_item(
                expected.id
            )
            for incoming in details.tracked_seasons:
                season = seasons.get(incoming.season_num)
                if season is None:
                    session.add(
                        Season(
                            media_item_id=expected.id,
                            season_num=incoming.season_num,
                            title=incoming.title,
                        )
                    )
                    changed = True
                elif season.title != incoming.title:
                    season.title = incoming.title
                    session.add(season)
                    changed = True
            current.last_synced_at = utc_now()
            session.add(current)
        if changed:
            await emit_library_item_upserted(
                expected.id, "sync", self._publisher, database=self._database
            )
            return JobOutcome.UPDATED, "seasons refreshed from TMDB"
        return JobOutcome.UNCHANGED, "seasons match TMDB"

    @staticmethod
    def _matches(current: MediaItem | None, expected: MediaItem) -> bool:
        return (
            current is not None
            and current.media_type == MediaType.SHOW
            and current.tmdb_id == expected.tmdb_id
            and current.server_item_id is None
            and current.server_removed_at is None
        )
