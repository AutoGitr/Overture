"""Coverage for artwork service helpers, proxying, clear/match orchestration."""

lazy import asyncio
lazy from types import SimpleNamespace
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture import protocols
lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, ServerType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.repositories.seasons import SeasonRepository
lazy from overture.schemas.art import ArtCandidate, ArtMatchResponse, SaveArtRequest
lazy from overture.services.art import service as module
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher, ArtMatchOutcome
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils import image
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.image import RateLimitedError
lazy from tests.factories import (
    MediaItemFactory,
    SeasonFactory,
)
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    database_for,
    make_download_service,
    make_local_assets,
    one_session,
    row_id,
    unused,
)


class FakePublisher:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, Any]] = []

    async def broadcast(self, event: str, payload: Any = None, **_kwargs: Any) -> None:
        self.broadcasts.append((event, payload))

    async def broadcast_built(self, builder: Any) -> bool:
        built = builder()
        if built is None:
            return False
        event, payload = built
        self.broadcasts.append((event, payload))
        return True


def _art_matcher(
    monkeypatch: pytest.MonkeyPatch,
    result: ArtMatchResponse,
    *,
    app_config: Settings,
    database: Database,
) -> tuple[ArtMatcher, list[dict[str, Any]]]:
    matcher = ArtMatcher(
        phash=PhashService(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=AssetStorage(app_config=app_config),
        ),
        provider_registry=NoopProviderRegistry(),
        candidates=unused(ArtCandidates),
        image_clients=unused(ProxyClientManager),
        app_config=app_config,
        database=database,
        compare_concurrency=2,
    )
    calls: list[dict[str, Any]] = []

    async def fake_match_item_art(**kwargs: Any) -> ArtMatchOutcome:
        calls.append(kwargs)
        return ArtMatchOutcome(result)

    monkeypatch.setattr(matcher, "match_item_art", fake_match_item_art)
    return matcher, calls


def _download_service(*, app_config: Settings, database: Database) -> DownloadService:
    return make_download_service(
        unused(protocols.EventPublisher),
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        image_cache=unused(ImageCache),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )


def _art_service(
    *,
    app_config: Settings,
    database: Database,
    matcher: ArtMatcher | None = None,
    downloads: DownloadService | None = None,
    publisher: FakePublisher | None = None,
    provider_registry: ProviderRegistry | None = None,
    tmdb_client: Any | None = None,
    image_clients: ProxyClientManager | None = None,
) -> module.ArtService:
    registry = provider_registry or NoopProviderRegistry()
    return module.ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=matcher or unused(ArtMatcher),
        downloads=downloads
        or _download_service(app_config=app_config, database=database),
        publisher=publisher or FakePublisher(),
        provider_registry=registry,
        candidates=ArtCandidates(
            database=database,
            provider_registry=registry,
            tmdb_client=tmdb_client or unused(TMDBClient),
            app_config=app_config,
        ),
        image_clients=image_clients or unused(ProxyClientManager),
        image_cache=unused(ImageCache),
    )


# --- art_owner ------------------------------------------------


async def test_art_target_returns_item_for_poster_and_background(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(id=1)
    assert (
        await SeasonRepository(db_session).art_owner(item, ArtType.POSTER, None) is item
    )
    assert (
        await SeasonRepository(db_session).art_owner(item, ArtType.BACKGROUND, None)
        is item
    )


async def test_art_target_returns_none_for_season_poster_without_season_id(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(id=1)
    assert (
        await SeasonRepository(db_session).art_owner(item, ArtType.SEASON_POSTER, None)
        is None
    )


async def test_art_target_looks_up_season_for_season_poster(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(id=None, server_item_id="s1", library_id="l1")
    db_session.add(item)
    await db_session.commit()
    season = season_factory(id=None, media_item_id=item.id)
    db_session.add(season)
    await db_session.commit()

    target = await SeasonRepository(db_session).art_owner(
        item, ArtType.SEASON_POSTER, season.id
    )
    assert target is not None
    assert target.id == season.id


async def test_art_target_rejects_a_season_owned_by_another_item(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    app_config: Settings,
) -> None:
    requested_item = media_item_factory(id=None, media_type=MediaType.SHOW)
    other_item = media_item_factory(id=None, media_type=MediaType.SHOW)
    db_session.add_all([requested_item, other_item])
    await db_session.flush()
    season = season_factory(id=None, media_item_id=other_item.id)
    db_session.add(season)
    await db_session.commit()

    assert (
        await SeasonRepository(db_session).art_owner(
            requested_item,
            ArtType.SEASON_POSTER,
            season.id,
        )
        is None
    )


# --- clear_art / clear_all_art / match_art (DB-backed orchestration) --------------


async def test_clear_art_raises_404_for_missing_item(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    database = database_for(one_session(db_session))
    service = _art_service(
        app_config=app_config, database=database, publisher=FakePublisher()
    )
    with pytest.raises(PublicServiceError) as exc_info:
        await service.clear(
            item_id=99999,
            art_type=ArtType.POSTER,
            season_id=None,
        )
    assert exc_info.value.status_code == 404


async def test_clear_art_forgets_the_selection_keeps_file_facts_and_broadcasts(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        server_item_id="s1",
        library_id="l1",
        art={
            "poster": {
                "url": "https://x/p.jpg",
                "file_hash": "h",
                "phash": "p",
            }
        },
    )
    db_session.add(item)
    await db_session.commit()

    database = database_for(one_session(db_session))
    publisher = FakePublisher()
    service = _art_service(
        app_config=app_config, database=database, publisher=publisher
    )
    result = await service.clear(
        item_id=row_id(item),
        art_type=ArtType.POSTER,
        season_id=None,
    )

    assert result.status == "cleared"
    await db_session.refresh(item)
    poster = read_art_slot(item, ArtType.POSTER)
    assert poster.url is None
    assert poster.file_hash == "h"
    assert poster.phash == "p"
    assert publisher.broadcasts[0][0] == "library.item.upserted"


async def test_clear_all_art_raises_404_for_missing_item(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    database = database_for(one_session(db_session))
    service = _art_service(
        app_config=app_config, database=database, publisher=FakePublisher()
    )
    with pytest.raises(PublicServiceError):
        await service.clear_all(99999)


async def test_clear_all_art_forgets_item_and_season_selections(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        server_item_id="s1",
        library_id="l1",
        art={
            "poster": {"url": "https://x/p.jpg", "file_hash": "p"},
            "background": {"url": "https://x/bg.jpg", "file_hash": "b"},
        },
    )
    db_session.add(item)
    await db_session.commit()
    season = season_factory(
        id=None,
        media_item_id=item.id,
        art={
            "season_poster": {
                "url": "https://x/season.jpg",
                "file_hash": "hash",
            }
        },
    )
    db_session.add(season)
    await db_session.commit()

    database = database_for(one_session(db_session))
    publisher = FakePublisher()
    service = _art_service(
        app_config=app_config, database=database, publisher=publisher
    )
    result = await service.clear_all(row_id(item))

    assert result.status == "cleared"
    await db_session.refresh(item)
    await db_session.refresh(season)
    assert read_art_slot(item, ArtType.POSTER).url is None
    assert read_art_slot(item, ArtType.BACKGROUND).url is None
    assert read_art_slot(season, ArtType.SEASON_POSTER).url is None
    assert read_art_slot(season, ArtType.SEASON_POSTER).file_hash == "hash"
    assert read_art_slot(item, ArtType.POSTER).file_hash == "p"
    assert read_art_slot(item, ArtType.BACKGROUND).file_hash == "b"


async def test_match_art_raises_404_for_missing_item(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    database = database_for(one_session(db_session))
    matcher, _calls = _art_matcher(
        monkeypatch, ArtMatchResponse(), app_config=app_config, database=database
    )
    service = _art_service(
        app_config=app_config,
        database=database,
        matcher=matcher,
        publisher=FakePublisher(),
    )
    with pytest.raises(PublicServiceError):
        await service.match(
            item_id=99999,
            art_type=ArtType.POSTER,
            threshold=5,
            season_id=None,
        )


async def test_match_art_refuses_at_once_while_an_image_host_is_paused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    database = database_for(one_session(db_session))
    matcher, calls = _art_matcher(
        monkeypatch, ArtMatchResponse(), app_config=app_config, database=database
    )
    service = _art_service(
        app_config=app_config,
        database=database,
        matcher=matcher,
        publisher=FakePublisher(),
    )
    image.IMAGE_HOST_PAUSES.limited("theposterdb.com")
    with pytest.raises(PublicServiceError) as exc_info:
        await service.match(item_id=1, art_type=ArtType.POSTER, threshold=5)
    assert exc_info.value.status_code == 503
    assert exc_info.value.message.startswith(
        "theposterdb.com is rate limiting requests; try again in "
    )
    assert calls == []


async def test_match_art_updates_item_timestamp_and_broadcasts(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(id=None, server_item_id="s1", library_id="l1")
    db_session.add(item)
    await db_session.commit()

    database = database_for(one_session(db_session))
    publisher = FakePublisher()
    matcher, _calls = _art_matcher(
        monkeypatch, ArtMatchResponse(), app_config=app_config, database=database
    )
    service = _art_service(
        app_config=app_config, database=database, matcher=matcher, publisher=publisher
    )

    response = await service.match(
        item_id=row_id(item),
        art_type=ArtType.POSTER,
        threshold=5,
        season_id=None,
    )

    assert response.matches == []
    await db_session.refresh(item)
    assert item.last_matched_at is not None
    assert publisher.broadcasts[0][0] == "library.item.upserted"


async def test_match_art_updates_season_timestamp_for_season_poster(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None, media_type=MediaType.SHOW, server_item_id="s1", library_id="l1"
    )
    db_session.add(item)
    await db_session.commit()
    season = season_factory(id=None, media_item_id=item.id)
    db_session.add(season)
    await db_session.commit()

    database = database_for(one_session(db_session))
    matcher, calls = _art_matcher(
        monkeypatch, ArtMatchResponse(), app_config=app_config, database=database
    )
    service = _art_service(
        app_config=app_config,
        database=database,
        matcher=matcher,
        publisher=FakePublisher(),
    )
    await service.match(
        item_id=row_id(item),
        art_type=ArtType.SEASON_POSTER,
        threshold=5,
        season_id=season.id,
    )

    await db_session.refresh(season)
    assert season.last_matched_at is not None
    assert calls[0]["include_overturedb"] is True


# --- save_art guard clauses (no network required) ----------------------------------


async def test_save_art_rejects_unsupported_image_format(
    *, app_config: Settings, database: Database
) -> None:
    service = _art_service(
        app_config=app_config,
        database=database,
        downloads=_download_service(app_config=app_config, database=database),
    )
    with pytest.raises(PublicServiceError) as exc_info:
        await service.save(
            item_id=1,
            art_type=ArtType.POSTER,
            body=SaveArtRequest(url="https://example.test/image.gif"),
            season_id=None,
        )
    assert exc_info.value.status_code == 400


async def test_save_art_rejects_private_url(
    *, app_config: Settings, database: Database
) -> None:
    service = _art_service(
        app_config=app_config,
        database=database,
        downloads=_download_service(app_config=app_config, database=database),
    )
    with pytest.raises(PublicServiceError) as exc_info:
        await service.save(
            item_id=1,
            art_type=ArtType.POSTER,
            body=SaveArtRequest(url="http://127.0.0.1/image.jpg"),
            season_id=None,
        )
    assert exc_info.value.status_code == 400
    assert "Private" in exc_info.value.message


async def test_save_art_refuses_at_once_to_measure_on_a_paused_host(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    async def accept(_target_url: str, **_kwargs: object) -> None:
        return None

    async def sniff(*_args: object, **_kwargs: object) -> tuple[int, int]:
        raise AssertionError("a paused host is not asked")

    monkeypatch.setattr(module, "_validate_art_url", accept)
    monkeypatch.setattr(module, "sniff_image_size", sniff)
    image.IMAGE_HOST_PAUSES.limited("image.tmdb.org")
    service = _art_service(app_config=app_config, database=database)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.save(
            item_id=1,
            art_type=ArtType.POSTER,
            body=SaveArtRequest(url="https://image.tmdb.org/t/p/original/a.jpg"),
        )
    assert exc_info.value.status_code == 503
    assert "image.tmdb.org is rate limiting requests" in exc_info.value.message


async def test_save_art_reports_a_rate_limit_met_while_measuring(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    async def accept(_target_url: str, **_kwargs: object) -> None:
        return None

    async def sniff(*_args: object, **_kwargs: object) -> tuple[int, int]:
        raise RateLimitedError("image.tmdb.org is rate limiting requests")

    monkeypatch.setattr(module, "_validate_art_url", accept)
    monkeypatch.setattr(module, "sniff_image_size", sniff)

    def no_headers(_url: str) -> dict[str, str]:
        return {}

    provider = SimpleNamespace(get_download_headers=no_headers)
    service = _art_service(
        app_config=app_config,
        database=database,
        provider_registry=NoopProviderRegistry(provider),
        image_clients=StaticImageClients(),
    )
    with pytest.raises(PublicServiceError) as exc_info:
        await service.save(
            item_id=1,
            art_type=ArtType.POSTER,
            body=SaveArtRequest(url="https://image.tmdb.org/t/p/original/a.jpg"),
        )
    assert exc_info.value.status_code == 503


async def test_save_art_rejects_source_links_that_name_no_image(
    *, app_config: Settings, database: Database
) -> None:
    service = _art_service(app_config=app_config, database=database)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.save(
            item_id=1,
            art_type=ArtType.POSTER,
            body=SaveArtRequest(url="https://theposterdb.com/set/12345"),
            season_id=None,
        )
    assert exc_info.value.status_code == 400
    assert "ThePosterDB" in exc_info.value.message


async def test_save_art_downloads_the_canonical_full_size_link(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    validated: list[str] = []

    async def stop_after_validation(target_url: str, **_kwargs: object) -> None:
        validated.append(target_url)
        raise PublicServiceError(418, "stop")

    monkeypatch.setattr(module, "_validate_art_url", stop_after_validation)
    service = _art_service(app_config=app_config, database=database)
    with pytest.raises(PublicServiceError):
        await service.save(
            item_id=1,
            art_type=ArtType.POSTER,
            body=SaveArtRequest(url="https://image.tmdb.org/t/p/w342/a.jpg?api_key=x"),
            season_id=None,
        )
    assert validated == ["https://image.tmdb.org/t/p/original/a.jpg"]


async def test_save_art_returns_and_announces_the_item_as_stored(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def accept(_target_url: str, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(module, "_validate_art_url", accept)
    db_session.add(media_item_factory())
    await db_session.commit()
    database = database_for(one_session(db_session))
    publisher = FakePublisher()
    service = _art_service(
        app_config=app_config, database=database, publisher=publisher
    )

    result = await service.save(
        item_id=1,
        art_type=ArtType.POSTER,
        body=SaveArtRequest(
            url="https://image.tmdb.org/t/p/original/a.jpg", width=1000, height=1500
        ),
    )

    assert result.selection.status == "enqueued"
    assert result.item.id == 1
    assert result.item.poster_url == "https://image.tmdb.org/t/p/original/a.jpg"
    assert publisher.broadcasts == [
        (
            "library.item.upserted",
            {"item": result.item.model_dump(mode="json"), "source": "art.save"},
        )
    ]


# --- get_art_sources guard clauses --------------------------------------------------


async def test_get_art_sources_raises_404_for_missing_item(
    db_session: AsyncSession,
    *,
    app_config: Settings,
) -> None:
    database = database_for(one_session(db_session))
    service = _art_service(
        app_config=app_config,
        database=database,
        provider_registry=NoopProviderRegistry(),
        tmdb_client=unused(TMDBClient),
    )
    with pytest.raises(PublicServiceError) as exc_info:
        await service.get_sources(
            item_id=99999,
            art_type=ArtType.POSTER,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("failed_source", [None, "tmdb", "plex"])
@pytest.mark.parametrize("art_type", [ArtType.POSTER, ArtType.SEASON_POSTER])
async def test_art_sources_fetch_independently_and_keep_successful_results(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    monkeypatch: pytest.MonkeyPatch,
    failed_source: str | None,
    art_type: ArtType,
    *,
    app_config: Settings,
) -> None:
    app_config.TMDB_API_KEY = SecretStr("test-key")
    saved_url = "https://public.test/selected.jpg"
    item = media_item_factory(
        id=None,
        server_item_id="server-1",
        library_id="library-1",
        media_type=MediaType.SHOW if art_type.owned_by_season else "movie",
        tmdb_id=123,
        art={"poster": {"url": saved_url}},
    )
    db_session.add(item)
    await db_session.commit()
    season_id = None
    if art_type.owned_by_season:
        season = season_factory(
            id=None,
            media_item_id=item.id,
            season_num=0,
            server_item_id="server-1",
            art={"season_poster": {"url": saved_url}},
        )
        db_session.add(season)
        await db_session.commit()
        season_id = season.id

    tmdb_started = asyncio.Event()
    server_started = asyncio.Event()

    async def tmdb_request(path: str, **kwargs: Any) -> dict[str, Any]:
        expected_path = (
            "/tv/123/season/0/images"
            if art_type.owned_by_season
            else "/movie/123/images"
        )
        assert path == expected_path
        assert kwargs["params"] == {"include_image_language": "en,null"}
        tmdb_started.set()
        await server_started.wait()
        if failed_source == "tmdb":
            raise httpx2.ConnectError("TMDB unavailable")
        return {"posters": [{"file_path": "/tmdb.jpg", "width": 100, "height": 150}]}

    async def server_candidates(server_id: str, requested_type: str) -> list[Any]:
        assert server_id == "server-1"
        assert requested_type == art_type
        server_started.set()
        await tmdb_started.wait()
        if failed_source == "plex":
            raise httpx2.ConnectError("Plex unavailable")
        return [ArtCandidate(url="https://public.test/plex.jpg", width=200, height=300)]

    tmdb = TMDBClient(app_config=app_config)
    monkeypatch.setattr(tmdb, "_get", tmdb_request)
    provider = SimpleNamespace(
        server_type=ServerType.PLEX, get_art_candidates=server_candidates
    )

    database = database_for(one_session(db_session))
    service = _art_service(
        app_config=app_config,
        database=database,
        provider_registry=NoopProviderRegistry(provider),
        tmdb_client=tmdb,
    )
    response = await asyncio.wait_for(
        service.get_sources(
            item_id=row_id(item),
            art_type=art_type,
            season_id=season_id,
        ),
        timeout=2,
    )

    assert response.current_url == saved_url
    assert [candidate.url for candidate in response.sources["tmdb"]] == (
        []
        if failed_source == "tmdb"
        else ["https://image.tmdb.org/t/p/original/tmdb.jpg"]
    )
    assert [candidate.url for candidate in response.sources["plex"]] == (
        [] if failed_source == "plex" else ["https://public.test/plex.jpg"]
    )


async def test_clear_season_posters_without_a_season_forgets_every_season(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        server_item_id="s1",
        library_id="l1",
        art={"poster": {"url": "https://x/p.jpg", "file_hash": "p"}},
    )
    db_session.add(item)
    await db_session.commit()
    seasons = [
        season_factory(
            id=None,
            media_item_id=item.id,
            season_num=number,
            art={"season_poster": {"url": f"https://x/{number}.jpg", "file_hash": "h"}},
        )
        for number in (1, 2)
    ]
    db_session.add_all(seasons)
    await db_session.commit()

    service = _art_service(
        app_config=app_config,
        database=database_for(one_session(db_session)),
        publisher=FakePublisher(),
    )
    result = await service.clear(row_id(item), ArtType.SEASON_POSTER)

    assert result.status == "cleared"
    for season in seasons:
        await db_session.refresh(season)
        assert read_art_slot(season, ArtType.SEASON_POSTER).url is None
        assert read_art_slot(season, ArtType.SEASON_POSTER).file_hash == "h"
    await db_session.refresh(item)
    assert read_art_slot(item, ArtType.POSTER).url == "https://x/p.jpg"
