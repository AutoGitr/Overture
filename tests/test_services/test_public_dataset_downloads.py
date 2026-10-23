"""Coverage for queue_overturedb_downloads_for_items selection logic."""

lazy from collections.abc import Iterable
lazy from typing import Any, override

lazy import pytest
lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    IncrementalThemeOrder,
    MediaType,
    ThemeBulkSource,
)
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.public_dataset import downloads as module
lazy from overture.services.public_dataset.index import CatalogPick
lazy from overture.utils.locks import KeyedLock
lazy from tests.factories import (
    MediaItemFactory,
    SeasonFactory,
)
lazy from tests.runtime_helpers import row_id


class FakeDownloads(DownloadService):
    def __init__(self, *, created: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self._created = created
        self._asset_locks = KeyedLock[int | str]()

    @property
    @override
    def asset_locks(self) -> KeyedLock[int | str]:
        return self._asset_locks

    @override
    async def committed(self, session: AsyncSession) -> None:
        pass

    @override
    async def queue_job(
        self, session: AsyncSession, target: JobTarget, *, supersede: bool = True
    ) -> tuple[str, bool]:
        assert not supersede
        self.calls.append(
            {
                "media_item_id": target.media_item_id,
                "job_type": target.job_type,
                "art_type": target.art_type,
                "target_url": target.target_url,
                "season_id": target.season_id,
            }
        )
        return "job-id", self._created


class FakeIndex:
    """Stands in for the OvertureDB rows a run would have resolved up front."""

    def __init__(
        self,
        art: dict[str, str] | None = None,
        youtube_id: str | None = None,
        youtube_id_overturedb: str | None = None,
        youtube_id_themerrdb: str | None = None,
        raises_for_item_id: int | None = None,
    ) -> None:
        self._art = art or {}
        self._youtube_id = youtube_id
        self._youtube_id_overturedb = youtube_id_overturedb
        self._youtube_id_themerrdb = youtube_id_themerrdb
        self._raises_for_item_id = raises_for_item_id

    def art_url(
        self,
        item: MediaItem,
        art_type: str,
        *,
        season: Season | None = None,
    ) -> str | None:
        if self._raises_for_item_id is not None and item.id == self._raises_for_item_id:
            raise ValueError("boom")
        return self._art.get(art_type)

    def theme(
        self, _item: MediaItem, sources: Iterable[ThemeBulkSource]
    ) -> CatalogPick:
        by_source = {
            ThemeBulkSource.OVERTUREDB: self._youtube_id_overturedb or self._youtube_id,
            ThemeBulkSource.THEMERRDB: self._youtube_id_themerrdb,
        }
        return CatalogPick(
            next((found for s in sources if (found := by_source.get(s))), None)
        )


def _bind_index(monkeypatch: pytest.MonkeyPatch, index: FakeIndex) -> None:
    """Hand the module a ready-made index instead of querying the dataset."""

    class _Builder:
        @staticmethod
        async def build(
            _session: AsyncSession, _items: object, **_kwargs: Any
        ) -> FakeIndex:
            return index

    monkeypatch.setattr(module, "PublicDatasetIndex", _Builder)


async def test_returns_default_stats_when_item_ids_empty(
    *, app_config: Settings, database: Database
) -> None:
    stats = await module.queue_overturedb_downloads_for_items(
        [],
        include_art=True,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=FakeDownloads(),
        app_config=app_config,
        database=database,
    )

    assert stats == module.QueuedDownloads()


async def test_returns_default_stats_when_no_flags_enabled(
    *, app_config: Settings, database: Database
) -> None:
    stats = await module.queue_overturedb_downloads_for_items(
        [1],
        include_art=False,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=FakeDownloads(),
        app_config=app_config,
        database=database,
    )

    assert stats == module.QueuedDownloads()


async def test_missing_item_is_skipped(
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [999],
        include_art=True,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats == module.QueuedDownloads()
    assert downloads.calls == []


async def test_queues_poster_and_background_for_incomplete_movie(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-1",
        library_id="lib-1",
        folder_path="/media/Movie One",
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(
        monkeypatch,
        FakeIndex(
            art={
                "poster": "https://example.test/poster.jpg",
                "background": "https://example.test/bg.jpg",
            }
        ),
    )
    downloads = FakeDownloads(created=True)

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=True,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.art == 2
    art_types = {call["art_type"] for call in downloads.calls}
    assert art_types == {"poster", "background"}


async def test_skips_art_type_that_is_already_complete(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-2",
        library_id="lib-1",
        folder_path="/media/Movie Two",
        art={"poster": {"file_hash": "abc123"}},
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(
        monkeypatch, FakeIndex(art={"background": "https://example.test/bg.jpg"})
    )
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=True,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.art == 1
    assert [c["art_type"] for c in downloads.calls] == ["background"]


async def test_no_candidates_means_no_job_queued(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-3",
        library_id="lib-1",
        folder_path="/media/Movie Three",
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(monkeypatch, FakeIndex())
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=True,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.art == 0
    assert downloads.calls == []


async def test_show_seasons_are_queued_and_zero_file_count_skipped(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        server_item_id="overture-4",
        library_id="lib-1",
        folder_path="/media/Show One",
    )
    db_session.add(item)
    await db_session.commit()

    empty_season = season_factory(
        id=None, media_item_id=item.id, season_num=0, file_count=0
    )
    complete_season = season_factory(
        id=None,
        media_item_id=item.id,
        season_num=1,
        file_count=5,
        art={"season_poster": {"file_hash": "hash"}},
    )
    incomplete_season = season_factory(
        id=None, media_item_id=item.id, season_num=2, file_count=8
    )
    db_session.add_all([empty_season, complete_season, incomplete_season])
    await db_session.commit()

    _bind_index(
        monkeypatch,
        FakeIndex(art={"season_poster": "https://example.test/season.jpg"}),
    )
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=True,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    # Only the incomplete, non-empty season should have been queued.
    assert stats.art == 1
    assert len(downloads.calls) == 1
    assert downloads.calls[0]["season_id"] == incomplete_season.id
    assert downloads.calls[0]["art_type"] == "season_poster"


async def test_created_false_does_not_increment_stats(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-5",
        library_id="lib-1",
        folder_path="/media/Movie Five",
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(
        monkeypatch, FakeIndex(art={"poster": "https://example.test/poster.jpg"})
    )
    downloads = FakeDownloads(created=False)

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=True,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.art == 0
    assert len(downloads.calls) == 1


async def test_theme_is_queued_when_incomplete(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-6",
        library_id="lib-1",
        folder_path="/media/Movie Six",
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(monkeypatch, FakeIndex(youtube_id="yt-abc"))
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.themes == 1
    assert downloads.calls[0]["job_type"] == "theme"
    assert downloads.calls[0]["target_url"] == "yt-abc"


@pytest.mark.parametrize("youtube_id", ["already-set", None])
async def test_existing_local_theme_is_never_replaced(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    youtube_id: str | None,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Polling fills missing files only, even when the file's source is unknown."""
    _bind_index(monkeypatch, FakeIndex(youtube_id="yt-abc"))
    item = media_item_factory(
        id=None,
        server_item_id="overture-7",
        library_id="lib-1",
        folder_path="/media/Movie Seven",
        theme_file_hash="theme-hash",
        youtube_id=youtube_id,
    )
    db_session.add(item)
    await db_session.commit()

    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.themes == 0
    assert downloads.calls == []


async def test_theme_not_queued_when_no_youtube_id_found(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-8",
        library_id="lib-1",
        folder_path="/media/Movie Eight",
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(monkeypatch, FakeIndex())
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.themes == 0
    assert downloads.calls == []


async def test_theme_priority_ordering(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-theme-prio",
        library_id="lib-1",
        folder_path="/media/Movie Priority",
    )
    db_session.add(item)
    await db_session.commit()

    _bind_index(
        monkeypatch,
        FakeIndex(
            youtube_id_overturedb="yt-overturedb",
            youtube_id_themerrdb="yt-themerrdb",
        ),
    )

    # When overturedb_themerrdb is requested, overturedb ID is chosen
    downloads_ov = FakeDownloads()
    stats_ov = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads_ov,
        app_config=app_config,
        database=database,
    )
    assert stats_ov.themes == 1
    assert downloads_ov.calls[0]["target_url"] == "yt-overturedb"

    # When themerrdb_overturedb is requested, themerrdb ID is chosen
    downloads_th = FakeDownloads()
    stats_th = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.THEMERRDB_OVERTUREDB,
        downloads=downloads_th,
        app_config=app_config,
        database=database,
    )
    assert stats_th.themes == 1
    assert downloads_th.calls[0]["target_url"] == "yt-themerrdb"

    # When theme_order is "off", no themes are queued
    downloads_off = FakeDownloads()
    stats_off = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads_off,
        app_config=app_config,
        database=database,
    )
    assert stats_off.themes == 0
    assert downloads_off.calls == []


async def test_theme_priority_fallback(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="overture-theme-fallback",
        library_id="lib-1",
        folder_path="/media/Movie Fallback",
    )
    db_session.add(item)
    await db_session.commit()

    # Only themerrdb ID is present
    _bind_index(
        monkeypatch,
        FakeIndex(
            youtube_id_overturedb=None,
            youtube_id_themerrdb="yt-only-themerr",
        ),
    )

    downloads = FakeDownloads()
    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(item)],
        include_art=False,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )
    assert stats.themes == 1
    assert downloads.calls[0]["target_url"] == "yt-only-themerr"


@pytest.mark.parametrize("failure", ["lookup", "commit"])
async def test_error_for_one_item_is_recorded_and_loop_continues(
    db_session: AsyncSession,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    broken = media_item_factory(
        id=None,
        server_item_id="overture-9",
        library_id="lib-1",
        folder_path="/media/Broken",
    )
    healthy = media_item_factory(
        id=None,
        server_item_id="overture-10",
        library_id="lib-1",
        folder_path="/media/Healthy",
    )
    db_session.add_all([broken, healthy])
    await db_session.commit()

    _bind_index(
        monkeypatch,
        FakeIndex(
            art={
                "poster": "https://example.test/poster.jpg",
                "background": "https://example.test/bg.jpg",
            },
            raises_for_item_id=row_id(broken) if failure == "lookup" else None,
        ),
    )
    if failure == "commit":
        commit = AsyncSession.commit
        first = True

        async def fail_first_commit(session: AsyncSession) -> None:
            nonlocal first
            if first:
                first = False
                raise SQLAlchemyError("Commit failed")
            await commit(session)

        monkeypatch.setattr(AsyncSession, "commit", fail_first_commit)
    downloads = FakeDownloads()

    stats = await module.queue_overturedb_downloads_for_items(
        [row_id(broken), row_id(healthy)],
        include_art=True,
        theme_order=IncrementalThemeOrder.OFF,
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    assert stats.errors == 1
    # The healthy item after the broken one should still have been processed.
    assert stats.art == 2
    assert len(downloads.calls) == (2 if failure == "lookup" else 4)
