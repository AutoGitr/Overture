"""Full sync refreshes saved, unconnected TMDB shows without losing selections."""

lazy from collections.abc import AsyncIterator
lazy from pathlib import Path
lazy from typing import override

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.db.models.art import ArtSlot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, ServerType
lazy from overture.integrations.tmdb import TMDBClient, TmdbDetails, TmdbSeason
lazy from overture.jobs.progress_log import JobLogEntry
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import SyncTally
lazy from overture.media_servers.adapters import ServerItem
lazy from overture.repositories.seasons import SeasonRepository
lazy from overture.services.sync.reconciler import LibraryReconciler, SyncResult
lazy from overture.services.sync.runner import run_sync
lazy from overture.services.sync.tmdb_seasons import TmdbSeasonSync
lazy from overture.utils.time import utc_now
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import JobProbe, NoopProviderRegistry


class TmdbStub(TMDBClient):
    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls: list[int] = []
        self.fail_first = fail_first

    @override
    async def get_details(
        self, media_type: MediaType, tmdb_id: int
    ) -> TmdbDetails | None:
        assert media_type == MediaType.SHOW
        self.calls.append(tmdb_id)
        if self.fail_first and tmdb_id == 1:
            raise httpx2.ConnectError("TMDB unavailable")
        return TmdbDetails(
            media_type=MediaType.SHOW,
            tmdb_id=tmdb_id,
            title="Show",
            year=2026,
            tvdb_id=None,
            imdb_id=None,
            poster_url=None,
            background_url=None,
            seasons=(
                TmdbSeason(0, "Specials", 1, None),
                TmdbSeason(1, "Season One", 10, None),
                TmdbSeason(2, "Season Two", 10, None),
                TmdbSeason(3, "Announced", 0, None),
            ),
        )


@pytest.mark.parametrize("fail_first", [False, True])
async def test_full_sync_without_server_refreshes_only_unconnected_shows(
    tmp_path: Path, app_config: Settings, database: Database, fail_first: bool
) -> None:
    app_config.TMDB_API_KEY = SecretStr("tmdb-test")
    client = TmdbStub(fail_first=fail_first)
    service = TmdbSeasonSync(
        app_config=app_config,
        database=database,
        tmdb_client=client,
        publisher=NullEventPublisher(),
    )
    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(id=1, title="First", media_type=MediaType.SHOW, tmdb_id=1),
                MediaItem(id=2, title="Second", media_type=MediaType.SHOW, tmdb_id=2),
                MediaItem(
                    id=3,
                    title="Connected",
                    media_type=MediaType.SHOW,
                    tmdb_id=3,
                    server_item_id="server-show",
                ),
                MediaItem(id=4, title="Movie", media_type=MediaType.MOVIE, tmdb_id=4),
                MediaItem(
                    id=5,
                    title="Removed",
                    media_type=MediaType.SHOW,
                    tmdb_id=5,
                    server_removed_at=utc_now(),
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Season(id=1, media_item_id=2, season_num=1, title="Old title"),
                Season(id=2, media_item_id=2, season_num=9, title="Retained season"),
            ]
        )
        await session.flush()
        session.add(
            ArtSlot(
                season_id=1,
                art_type=ArtType.SEASON_POSTER,
                url="https://image.tmdb.org/t/p/original/chosen.jpg",
            )
        )

    class EmptyServer:
        server_type = ServerType.PLEX

        async def iter_items(
            self, library_ids: list[str] | None = None
        ) -> AsyncIterator[list[ServerItem]]:
            for page in ():
                yield page

    class NothingToReconcile(LibraryReconciler):
        def __init__(self) -> None:
            pass

        @override
        async def sync_staged(self, *_args: object, **_kwargs: object) -> SyncResult:
            return SyncResult()

    for run in range(2):
        probe = JobProbe()
        await run_sync(
            probe.context,
            provider_registry=NoopProviderRegistry(EmptyServer()),
            reconciler=NothingToReconcile(),
            config_dir=tmp_path,
            tmdb_seasons=service,
        )
        _, result = probe.terminal()
        assert result["total"] == result["done"] == 2
        assert result["errors"] == int(fail_first)
        assert result["updated"] == (0 if run else 2 - int(fail_first))
        assert result["unchanged"] == (2 - int(fail_first) if run else 0)
    # Shows are fetched concurrently, each once per run.
    assert sorted(client.calls) == [1, 1, 2, 2]
    async with database.read_session() as session:
        seasons = await SeasonRepository(session).map_by_number_for_item(2)
        assert set(seasons) == {0, 1, 2, 9}
        assert seasons[1].title == "Season One"
        assert seasons[1].art_slots[0].url == (
            "https://image.tmdb.org/t/p/original/chosen.jpg"
        )
        assert all(season.server_item_id is None for season in seasons.values())
        assert all(season.file_count == 0 for season in seasons.values())


async def test_unconfigured_tmdb_and_show_linked_after_planning_are_skipped(
    app_config: Settings, database: Database
) -> None:
    client = TmdbStub()
    service = TmdbSeasonSync(
        app_config=app_config,
        database=database,
        tmdb_client=client,
        publisher=NullEventPublisher(),
    )
    async with database.write_session() as session:
        session.add(MediaItem(id=1, title="Show", media_type=MediaType.SHOW, tmdb_id=1))
    app_config.TMDB_API_KEY = SecretStr("")
    assert await service.targets() == []
    app_config.TMDB_API_KEY = SecretStr("tmdb-test")
    [expected] = await service.targets()
    async with database.write_session() as session:
        current = await session.get(MediaItem, 1)
        assert current is not None
        current.server_item_id = "now-connected"
        session.add(current)
    probe = JobProbe()
    async with run_managed_job(probe.context, SyncTally()) as job:
        await job.started()
        await job.planned(1)
        await service.run([expected], job)
    assert probe.terminal()[1]["done"] == 1
    assert (
        JobLogEntry.model_validate(probe.events[-2][1]["log"])
        .format()
        .startswith("Skipped Show - ")
    )
    assert client.calls == []
