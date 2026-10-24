"""TMDB results open unsaved and are stored by their first selection."""

lazy from collections.abc import Sequence
lazy from dataclasses import replace
lazy from typing import Any, Literal, override

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot, write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetItem
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    CatalogMediaType,
    MediaType,
    ThemeIdSource,
    TmdbLanguageFilter,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import (
    TMDBClient,
    TmdbCollection,
    TmdbDetails,
    TmdbSeason,
    TmdbTitle,
)
lazy from overture.schemas.art import ArtCandidate, SaveArtRequest
lazy from overture.schemas.public_dataset import CatalogDraftUpdate
lazy from overture.schemas.themes import SelectThemeRequest, ThemeSearchResult
lazy from overture.schemas.tmdb import TmdbItemResult
lazy from overture.services.art import service as art_module
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.public_dataset.browse import CatalogBrowser
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.services.themes.service import ThemesService
lazy from overture.services.tmdb_items import TmdbItemsService
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.locks import KeyedLock
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.factories import MediaItemFactory, PublicDatasetItemFactory
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    NoopTmdb,
    NoopYoutube,
    unused,
)

IMAGE = "https://image.tmdb.org/t/p/original"
MATRIX = TmdbDetails(
    media_type=MediaType.MOVIE,
    tmdb_id=603,
    title="The Matrix",
    year=1999,
    tvdb_id=None,
    imdb_id="tt0133093",
    poster_url=f"{IMAGE}/matrix.jpg",
    background_url=None,
    seasons=(),
)
SHOW = TmdbDetails(
    media_type=MediaType.SHOW,
    tmdb_id=1399,
    title="Show",
    year=2011,
    tvdb_id=121361,
    imdb_id=None,
    poster_url=None,
    background_url=None,
    seasons=(
        TmdbSeason(season_num=0, title="Specials", episode_count=2, poster_url=None),
        TmdbSeason(season_num=1, title="Season 1", episode_count=10, poster_url=None),
        TmdbSeason(season_num=2, title="Announced", episode_count=0, poster_url=None),
    ),
)
COLLECTION = TmdbCollection(
    tmdb_id=2344,
    title="The Matrix Collection",
    poster_url=None,
    parts=(
        TmdbTitle(604, "The Matrix Reloaded", 2003, "2003-05-15", None),
        TmdbTitle(603, "The Matrix", 1999, "1999-03-31", None),
    ),
)
POSTER = SaveArtRequest(url=f"{IMAGE}/chosen.jpg", width=1000, height=1500)


class FakeTmdb(NoopTmdb):
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def _check(self, call: str, arg: object) -> None:
        self.calls.append((call, arg))
        if self.error:
            raise self.error

    @override
    async def search(
        self, kind: Literal["movie", "tv", "collection"], query: str
    ) -> tuple[TmdbTitle, ...]:
        self._check("search", kind)
        if kind == "collection":
            return (COLLECTION.summary,)
        return (MATRIX.summary,) if kind == "movie" else (SHOW.summary,)

    @override
    async def get_details(
        self, media_type: MediaType, tmdb_id: int
    ) -> TmdbDetails | None:
        self._check("details", tmdb_id)
        return {(MediaType.MOVIE, 603): MATRIX, (MediaType.SHOW, 1399): SHOW}.get(
            (media_type, tmdb_id)
        )

    @override
    async def get_collection(self, collection_id: int) -> TmdbCollection | None:
        self._check("collection", collection_id)
        return COLLECTION if collection_id == COLLECTION.tmdb_id else None


class FakeYoutube(NoopYoutube):
    @override
    async def search(
        self,
        query: str = "",
        limit: int = 10,
        video_ids: Sequence[str] | None = None,
        *,
        wait: bool = True,
    ) -> list[ThemeSearchResult]:
        return [
            ThemeSearchResult(id=video_id, title="Main Theme", duration=95)
            for video_id in video_ids or []
        ]


@pytest.fixture
def tmdb_config(app_config: Settings) -> Settings:
    app_config.TMDB_API_KEY = SecretStr("test-key")
    return app_config


@pytest.fixture(autouse=True)
def public_urls(monkeypatch: pytest.MonkeyPatch, public_art_hosts: None) -> None:
    """Accept the test image hosts without resolving them."""

    async def public(_url: str, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(art_module, "is_private_url", public)


def _asset_services(
    *,
    app_config: Settings,
    database: Database,
    tmdb: TMDBClient,
    downloads: DownloadService | None = None,
) -> tuple[art_module.ArtService, ThemesService]:
    asset_storage = AssetStorage(app_config=app_config)
    downloads_svc = downloads or unused(DownloadService)
    return (
        art_module.ArtService(
            app_config=app_config,
            database=database,
            asset_storage=asset_storage,
            matcher=unused(ArtMatcher),
            downloads=downloads_svc,
            publisher=NullEventPublisher(),
            provider_registry=NoopProviderRegistry(),
            candidates=ArtCandidates(
                database=database,
                provider_registry=NoopProviderRegistry(),
                tmdb_client=tmdb,
                app_config=app_config,
            ),
            image_clients=unused(ProxyClientManager),
            image_cache=unused(ImageCache),
        ),
        ThemesService(
            database=database,
            asset_storage=asset_storage,
            downloads=downloads_svc,
            publisher=NullEventPublisher(),
            youtube_resolver=FakeYoutube(),
        ),
    )


def _service(
    *,
    app_config: Settings,
    database: Database,
    tmdb: TMDBClient | None = None,
    downloads: DownloadService | None = None,
) -> TmdbItemsService:
    tmdb_client = tmdb or FakeTmdb()
    downloads = downloads or RecordingDownloads()
    art, themes = _asset_services(
        app_config=app_config,
        database=database,
        tmdb=tmdb_client,
        downloads=downloads,
    )
    return TmdbItemsService(
        app_config=app_config,
        database=database,
        tmdb_client=tmdb_client,
        art=art,
        themes=themes,
        downloads=downloads,
        publisher=NullEventPublisher(),
        catalog=CatalogBrowser(database=database, app_config=app_config),
    )


async def _items(db_session: AsyncSession) -> list[MediaItem]:
    db_session.expire_all()
    return list((await db_session.exec(select(MediaItem))).all())


async def test_a_title_search_lists_movies_then_collections(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    tmdb_config: Settings,
    database: Database,
) -> None:
    db_session.add(media_item_factory(id=7, tmdb_id=603))
    await db_session.commit()

    response = await _service(app_config=tmdb_config, database=database).search(
        MediaType.MOVIE, " matrix "
    )

    assert [
        (result.kind, result.tmdb_id, getattr(result, "existing_item_id", None))
        for result in response.results
    ] == [("item", 603, 7), ("collection", 2344, None)]


async def test_a_number_is_looked_up_as_an_id_and_searched_as_a_title(
    *, tmdb_config: Settings, database: Database
) -> None:
    tmdb = FakeTmdb()
    service = _service(app_config=tmdb_config, database=database, tmdb=tmdb)

    movies = await service.search(MediaType.MOVIE, "603")
    movie_calls = sorted(tmdb.calls, key=str)
    tmdb.calls.clear()
    # "1917" names no show, so only the title search finds anything.
    shows = await service.search(MediaType.SHOW, "1917")

    # The ID and the title search both find The Matrix; it is listed once.
    assert [(result.kind, result.tmdb_id) for result in movies.results] == [
        ("item", 603),
        ("collection", 2344),
    ]
    assert movie_calls == [
        ("collection", 603),
        ("details", 603),
        ("search", "collection"),
        ("search", "movie"),
    ]
    assert [result.tmdb_id for result in shows.results] == [1399]
    assert sorted(tmdb.calls, key=str) == [("details", 1917), ("search", "tv")]


async def test_a_collection_lists_its_movies_oldest_first(
    *, tmdb_config: Settings, database: Database
) -> None:
    response = await _service(app_config=tmdb_config, database=database).collection(
        2344
    )

    assert [item.tmdb_id for item in response.items] == [603, 604]


@pytest.mark.parametrize("draft_poster", [f"{IMAGE}/draft.jpg", None])
async def test_catalog_members_use_only_catalog_or_draft_artwork(
    draft_poster: str | None,
    db_session: AsyncSession,
    *,
    tmdb_config: Settings,
    database: Database,
) -> None:
    class Tmdb(FakeTmdb):
        @override
        async def get_collection(self, collection_id: int) -> TmdbCollection:
            return replace(
                COLLECTION,
                parts=tuple(
                    replace(part, poster_url=f"{IMAGE}/tmdb-{part.tmdb_id}.jpg")
                    for part in (
                        *COLLECTION.parts,
                        TmdbTitle(605, "Missing", 2005, None, None),
                    )
                ),
            )

    library = MediaItem(media_type=MediaType.MOVIE, tmdb_id=605, title="Library movie")
    write_art_slot(
        library, ArtType.POSTER, url=f"{IMAGE}/library.jpg", file_hash="local"
    )
    db_session.add_all(
        [
            library,
            PublicDatasetItem(
                media_type=MediaType.MOVIE,
                tmdb_id=603,
                title="Catalog Matrix",
                year=1999,
                poster_url=f"{IMAGE}/catalog.jpg",
            ),
            PublicDatasetItem(
                media_type=MediaType.MOVIE,
                tmdb_id=604,
                title="Unillustrated movie",
                year=2003,
            ),
        ]
    )
    await db_session.commit()
    await enable_public_dataset(db_session)
    browser = CatalogBrowser(database=database, app_config=tmdb_config)
    service = _service(app_config=tmdb_config, database=database, tmdb=Tmdb())

    async def members() -> dict[int, TmdbItemResult]:
        response = await service.collection(2344, artwork_source="overturedb")
        return {member.tmdb_id: member for member in response.items}

    original = await members()
    assert original[603].poster_url == f"{IMAGE}/catalog.jpg"
    assert (
        original[603].poster_preview_url
        == "https://image.tmdb.org/t/p/w342/catalog.jpg"
    )
    assert original[603].title == "Catalog Matrix"
    assert original[604].catalog_entry_key == "tmdb-604"
    assert original[604].poster_url is None
    assert original[605].catalog_entry_key is None
    assert original[605].poster_url is None
    assert original[605].existing_item_id == library.id

    await browser.save_draft(
        CatalogMediaType.MOVIE,
        "tmdb-603",
        CatalogDraftUpdate(poster_url=draft_poster, tmdb_id=606),
    )
    drafted = await members()
    assert drafted[603].poster_url == draft_poster
    assert drafted[603].catalog_entry_key == "tmdb-603"
    if draft_poster is None:
        assert drafted[603].poster_preview_url is None
    await browser.discard_draft(CatalogMediaType.MOVIE, "tmdb-603")
    assert (await members())[603].poster_url == f"{IMAGE}/catalog.jpg"

    tmdb = await service.collection(2344)
    assert all(
        member.poster_url == f"{IMAGE}/tmdb-{member.tmdb_id}.jpg"
        for member in tmdb.items
    )


async def test_catalog_member_artwork_requires_an_enabled_catalog(
    *, tmdb_config: Settings, database: Database
) -> None:
    with pytest.raises(PublicServiceError, match="disabled") as exc:
        await _service(app_config=tmdb_config, database=database).collection(
            2344, artwork_source="overturedb"
        )
    assert exc.value.status_code == 409


async def test_the_preview_names_a_stored_item_matched_by_any_id(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    tmdb_config: Settings,
    database: Database,
) -> None:
    db_session.add(media_item_factory(id=9, media_type=MediaType.SHOW, tvdb_id=121361))
    await db_session.commit()
    service = _service(app_config=tmdb_config, database=database)

    show = await service.preview(MediaType.SHOW, 1399)
    movie = await service.preview(MediaType.MOVIE, 603)

    assert show.existing_item_id == 9
    assert [season.season_num for season in show.seasons] == [0, 1]
    assert movie.existing_item_id is None
    # The preview the sidebar's search result shows, so the poster appears at once.
    assert movie.poster_preview_url == "https://image.tmdb.org/t/p/w342/matrix.jpg"


async def test_the_first_artwork_stores_the_item_and_records_only_the_choice(
    db_session: AsyncSession, *, tmdb_config: Settings, database: Database
) -> None:
    service = _service(app_config=tmdb_config, database=database)

    first = await service.save_art(MediaType.MOVIE, 603, ArtType.POSTER, None, POSTER)
    again = await service.save_art(
        MediaType.MOVIE,
        603,
        ArtType.BACKGROUND,
        None,
        SaveArtRequest(url=f"{IMAGE}/bg.jpg", width=1920, height=1080),
    )

    assert first.selection.status == "selected"
    assert first.selection.job_id is None
    assert again.item.id == first.item.id
    assert again.item.art_status == "complete"
    (item,) = await _items(db_session)
    assert (item.title, item.year, item.tmdb_id, item.imdb_id, item.folder_path) == (
        "The Matrix",
        1999,
        603,
        "tt0133093",
        None,
    )
    assert read_art_slot(item, ArtType.POSTER).url == f"{IMAGE}/chosen.jpg"


async def test_a_refused_choice_stores_nothing(
    db_session: AsyncSession, *, tmdb_config: Settings, database: Database
) -> None:
    service = _service(app_config=tmdb_config, database=database)

    with pytest.raises(PublicServiceError) as exc_info:
        await service.save_art(
            MediaType.MOVIE,
            603,
            ArtType.POSTER,
            None,
            SaveArtRequest(url=f"{IMAGE}/wide.jpg", width=1920, height=1080),
        )

    assert exc_info.value.status_code == 400
    assert await _items(db_session) == []


async def test_a_season_poster_stores_the_show_with_its_seasons(
    db_session: AsyncSession, *, tmdb_config: Settings, database: Database
) -> None:
    service = _service(app_config=tmdb_config, database=database)

    with pytest.raises(PublicServiceError):
        await service.save_art(MediaType.SHOW, 1399, ArtType.SEASON_POSTER, 2, POSTER)
    response = await service.save_art(
        MediaType.SHOW, 1399, ArtType.SEASON_POSTER, 1, POSTER
    )

    seasons = (
        await db_session.exec(select(Season).order_by(col(Season.season_num)))
    ).all()
    assert [(season.season_num, season.file_count) for season in seasons] == [
        (0, 0),
        (1, 0),
    ]
    assert read_art_slot(seasons[1], ArtType.SEASON_POSTER).url == POSTER.url
    assert response.item.tvdb_id == 121361


async def test_the_first_theme_stores_the_item_with_the_video_details(
    db_session: AsyncSession, *, tmdb_config: Settings, database: Database
) -> None:
    response = await _service(app_config=tmdb_config, database=database).select_theme(
        MediaType.MOVIE, 603, SelectThemeRequest(youtube_id="abcDEF123_4")
    )

    assert response.selection.status == "selected"
    assert response.item.theme_status == "complete"
    (item,) = await _items(db_session)
    assert (
        item.youtube_id,
        item.youtube_id_source,
        item.youtube_title,
        item.youtube_duration,
    ) == ("abcDEF123_4", ThemeIdSource.SELECTION, "Main Theme", 95)


async def test_unsaved_items_see_overturedb_artwork(
    db_session: AsyncSession,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    tmdb_config: Settings,
    database: Database,
) -> None:
    db_session.add_all(
        [
            TaskSchedule(
                task_name="public_dataset",
                enabled=True,
                cron_expression="0 0 * * *",
                payload={},
            ),
            public_dataset_item_factory(
                tmdb_id=603,
                poster_url=f"{IMAGE}/curated.jpg",
                youtube_id_overturedb="abcDEF123_4",
            ),
        ]
    )
    await db_session.commit()
    service = _service(app_config=tmdb_config, database=database)

    sources = await service.art_sources(MediaType.MOVIE, 603, ArtType.POSTER, None)
    dataset = await service.public_dataset_sources(MediaType.MOVIE, 603)

    assert [c.url for c in sources.sources["overturedb"]] == [f"{IMAGE}/curated.jpg"]
    assert dataset.item is not None
    assert dataset.item.youtube_id_overturedb == "abcDEF123_4"
    assert await _items(db_session) == []


async def test_tmdb_must_be_configured_and_reachable(
    app_config: Settings, database: Database
) -> None:
    with pytest.raises(PublicServiceError) as unset:
        await _service(app_config=app_config, database=database).search(
            MediaType.MOVIE, "matrix"
        )
    app_config.TMDB_API_KEY = SecretStr("test-key")
    failing = FakeTmdb(error=httpx2.ConnectError("down"))
    with pytest.raises(PublicServiceError) as down:
        await _service(app_config=app_config, database=database, tmdb=failing).preview(
            MediaType.MOVIE, 603
        )
    with pytest.raises(PublicServiceError) as missing:
        await _service(app_config=app_config, database=database).preview(
            MediaType.MOVIE, 1
        )

    assert (unset.value.status_code, down.value.status_code) == (503, 502)
    assert missing.value.status_code == 404


async def test_a_stored_item_without_a_folder_records_choices_only(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    tmdb_config: Settings,
    database: Database,
) -> None:
    db_session.add(
        media_item_factory(id=5, folder_path=None, server_item_id=None, library_id=None)
    )
    await db_session.commit()
    downloads = RecordingDownloads()
    art_service, themes = _asset_services(
        app_config=tmdb_config, database=database, tmdb=FakeTmdb(), downloads=downloads
    )

    art = await art_service.save(5, ArtType.POSTER, POSTER)
    theme = await themes.select(5, "abcDEF123_4")
    with pytest.raises(PublicServiceError) as server_art:
        await art_service.save(
            5,
            ArtType.BACKGROUND,
            SaveArtRequest(
                url="http://127.0.0.1:32400/library/metadata/1/art.jpg",
                width=1920,
                height=1080,
            ),
        )

    assert (art.selection.status, art.selection.job_id, theme.selection.status) == (
        "selected",
        None,
        "selected",
    )
    assert server_art.value.status_code == 400
    assert downloads.jobs == []
    (item,) = await _items(db_session)
    assert read_art_slot(item, ArtType.POSTER).url == POSTER.url
    assert item.youtube_id_source == ThemeIdSource.SELECTION


class RecordingDownloads(DownloadService):
    def __init__(self) -> None:
        self.jobs: list[JobTarget] = []
        self.committed_jobs: list[JobTarget] = []
        self._asset_locks = KeyedLock[int | str]()

    @property
    @override
    def asset_locks(self) -> KeyedLock[int | str]:
        return self._asset_locks

    @override
    async def committed(self, session: AsyncSession) -> None:
        self.committed_jobs = list(self.jobs)

    @override
    async def queue_job(
        self, session: AsyncSession, target: JobTarget, *, supersede: bool = True
    ) -> tuple[str, bool]:
        self.jobs.append(target)
        return f"job-{len(self.jobs)}", True


async def test_tmdb_item_with_folder_enqueues_download_and_wakes_worker(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    tmdb_config: Settings,
    database: Database,
) -> None:
    db_session.add(
        media_item_factory(
            id=7,
            tmdb_id=603,
            media_type=MediaType.MOVIE,
            title="The Matrix",
            folder_path="/media/movies/The Matrix (1999)",
        )
    )
    await db_session.commit()
    downloads = RecordingDownloads()
    service = _service(
        app_config=tmdb_config,
        database=database,
        tmdb=FakeTmdb(),
        downloads=downloads,
    )

    art = await service.save_art(MediaType.MOVIE, 603, ArtType.POSTER, None, POSTER)
    assert art.selection.status == "enqueued"
    assert art.selection.job_id == "job-1"
    assert downloads.committed_jobs == downloads.jobs
    assert downloads.jobs == [JobTarget.art(7, ArtType.POSTER, POSTER.url)]

    theme = await service.select_theme(
        MediaType.MOVIE, 603, SelectThemeRequest(youtube_id="abcDEF123_4")
    )
    assert theme.selection.status == "enqueued"
    assert theme.selection.job_id == "job-2"
    assert downloads.committed_jobs == downloads.jobs
    assert downloads.jobs[1] == JobTarget.theme(7, "abcDEF123_4")


async def test_catalog_collection_art_uses_saved_candidate_policy(
    tmdb_config: Settings, database: Database
) -> None:
    class CollectionArtTmdb(FakeTmdb):
        @override
        async def art_candidates(
            self,
            media_type: MediaType | CatalogMediaType,
            tmdb_id: int,
            art_type: ArtType,
            *,
            season_num: int | None = None,
            language_filter: TmdbLanguageFilter = TmdbLanguageFilter.EN_NULL,
        ) -> list[ArtCandidate]:
            assert media_type == CatalogMediaType.COLLECTION
            assert tmdb_id == 10
            assert language_filter == TmdbLanguageFilter.EN_NULL
            return [
                ArtCandidate(
                    url=f"{IMAGE}/poster.jpg",
                    width=1000,
                    height=1500,
                    art_type=art_type,
                    source="tmdb",
                ),
                ArtCandidate(
                    url=f"{IMAGE}/wrong-shape.jpg",
                    width=1000,
                    height=1000,
                    art_type=art_type,
                    source="tmdb",
                ),
            ]

    service = _service(
        app_config=tmdb_config, database=database, tmdb=CollectionArtTmdb()
    )
    result = await service.art_sources(
        CatalogMediaType.COLLECTION, 10, ArtType.POSTER, None
    )
    assert [art.url for art in result.sources["tmdb"]] == [f"{IMAGE}/poster.jpg"]
    with pytest.raises(PublicServiceError, match="Collections have no season posters"):
        await service.art_sources(
            CatalogMediaType.COLLECTION, 10, ArtType.SEASON_POSTER, 1
        )
    async with database.read_session() as session:
        assert await _items(session) == []
