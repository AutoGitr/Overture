"""Coverage for collection listing, theme, matching, monitoring and image actions."""

lazy from collections.abc import Collection
lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from fastapi.responses import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.media_collection import (
    MediaCollection,
    MediaCollectionMember,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    ImageSize,
    MediaType,
    ServerAsset,
    ServerType,
)
lazy from overture.integrations.mdblist import MDBListClient
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.media_servers.adapters import ProviderImageRequest
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.collections import (
    SetCollectionThemeRequest,
)
lazy from overture.schemas.common import Status
lazy from overture.services.art.service import ArtService
lazy from overture.services.collections import service as module
lazy from overture.services.downloads.queue import AssetScope, JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.scheduler import SchedulerService
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.locks import KeyedLock
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.runtime_helpers import NoopProviderRegistry, unused


class FakePlex(PlexProvider):
    """A Plex provider that records what it was asked instead of calling Plex."""

    def __init__(
        self, *, app_config: Settings, delete_error: Exception | None = None
    ) -> None:
        super().__init__(app_config=app_config)
        self._delete_error = delete_error
        self.deleted_theme_for: list[str] = []
        self.image_requests: list[tuple[str, ArtType, ImageSize | None, str]] = []

    @override
    async def delete_collection_theme(self, server_item_id: str) -> None:
        if self._delete_error:
            raise self._delete_error
        self.deleted_theme_for.append(server_item_id)

    @override
    async def build_collection_image_request(
        self,
        server_item_id: str,
        art_type: ArtType,
        size: ImageSize | None,
        *,
        current_url: str,
    ) -> ProviderImageRequest:
        self.image_requests.append((server_item_id, art_type, size, current_url))
        return ProviderImageRequest(url="https://example.test/img", headers={})


class FakeDownloads(DownloadService):
    """Records the targets queued."""

    def __init__(self) -> None:
        self.targets: list[JobTarget] = []
        self._asset_locks = KeyedLock[int | str]()

    @property
    @override
    def asset_locks(self) -> KeyedLock[int | str]:
        return self._asset_locks

    @override
    async def queue_job(
        self, session: AsyncSession, target: JobTarget, *, supersede: bool = True
    ) -> tuple[str, bool]:
        self.targets.append(target)
        return "job-1", True

    @override
    async def cancel_assets(self, session: AsyncSession, scope: AssetScope) -> None:
        pass

    @override
    async def committed(self, session: AsyncSession) -> None:
        pass


class FakePublisher:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, Any]] = []

    async def broadcast(self, event: str, payload: Any = None, **_kwargs: Any) -> None:
        self.broadcasts.append((event, payload))

    async def broadcast_built(self, builder: Any) -> bool:
        raise AssertionError("Collections broadcast their events directly")


def _service(
    *,
    app_config: Settings,
    database: Database,
    provider: Any | None = None,
    publisher: FakePublisher | None = None,
    downloads: FakeDownloads | None = None,
    supported: bool = True,
) -> module.CollectionsService:
    return module.CollectionsService(
        tmdb=unused(TMDBClient),
        mdblist=unused(MDBListClient),
        scheduler=unused(SchedulerService),
        art=unused(ArtService),
        database=database,
        provider_registry=NoopProviderRegistry(
            provider or FakePlex(app_config=app_config), collections=supported
        ),
        publisher=publisher or FakePublisher(),
        downloads=downloads or FakeDownloads(),
        proxy_clients=unused(ProxyClientManager),
        app_config=app_config,
    )


async def _collection(
    session: AsyncSession, server_id: str = "c1", **fields: Any
) -> MediaCollection:
    row = MediaCollection(
        server_item_id=server_id,
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        title=f"Collection {server_id}",
        last_synced_at=utc_now(),
        **fields,
    )
    session.add(row)
    await session.commit()
    return row


async def test_every_action_rejects_a_server_without_collections(
    *, app_config: Settings, database: Database
) -> None:
    service = _service(app_config=app_config, database=database, supported=False)
    for call in (
        service.list_collections(MediaType.MOVIE),
        service.get_collection(1, MediaType.MOVIE),
        service.set_collection_theme(
            1,
            SetCollectionThemeRequest(youtube_id="a" * 11, media_type=MediaType.MOVIE),
        ),
        service.proxy_collection_image(1, ArtType.POSTER, None),
    ):
        with pytest.raises(PublicServiceError) as exc_info:
            await call
        assert exc_info.value.status_code == 400


async def test_list_collections_shows_listed_rows_with_their_catalog_themes(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _collection(db_session, "c1", tmdb_collection_id=10)
    await _collection(db_session, "c2", server_theme_id="/theme/1")
    # Kept from before the first sync: not shown until a sync lists it.
    db_session.add(
        MediaCollection(
            server_item_id="old",
            media_type=MediaType.MOVIE,
            server_type=ServerType.PLEX,
        )
    )
    db_session.add(
        PublicDatasetCollection(
            tmdb_id=10, title="Star Wars Collection", youtube_id_overturedb="a" * 11
        )
    )
    await db_session.commit()
    service = _service(app_config=app_config, database=database)

    disabled = await service.list_collections(MediaType.MOVIE)
    await enable_public_dataset(db_session)
    enabled = {c.id: c for c in await service.list_collections(MediaType.MOVIE)}

    assert sorted(c.id for c in disabled) == [1, 2]
    assert not any(c.public_dataset_complete for c in disabled)
    assert enabled[1].public_dataset_complete is True
    assert enabled[2].has_theme is True
    assert enabled[2].theme_status == "partial"
    assert await service.list_collections(MediaType.SHOW) == []


async def test_get_collection_lists_members_and_catalog_candidates(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    row = await _collection(db_session, tmdb_collection_id=10)
    newer = MediaItem(media_type=MediaType.MOVIE, title="Empire", year=1980)
    write_art_slot(
        newer,
        ArtType.POSTER,
        url="https://image.tmdb.org/t/p/original/empire.jpg",
        file_hash="poster-hash",
    )
    older = MediaItem(media_type=MediaType.MOVIE, title="Star Wars", year=1977)
    db_session.add_all([newer, older])
    await db_session.flush()
    db_session.add_all(
        MediaCollectionMember(collection_id=row.id or 0, media_item_id=item.id or 0)
        for item in (newer, older)
    )
    db_session.add(
        PublicDatasetCollection(
            tmdb_id=10, title="Star Wars Collection", youtube_id_themerrdb="b" * 11
        )
    )
    await db_session.commit()
    await enable_public_dataset(db_session)

    detail = await _service(app_config=app_config, database=database).get_collection(
        1, MediaType.MOVIE
    )

    assert [member.title for member in detail.members] == ["Star Wars", "Empire"]
    assert detail.members[1].poster_hash == "poster-hash"
    assert (
        detail.members[1].poster_preview_url
        == "https://image.tmdb.org/t/p/w342/empire.jpg"
    )
    assert detail.catalog_title == "Star Wars Collection"
    assert detail.youtube_id_themerrdb == "b" * 11
    assert detail.theme_unavailable is None


async def test_get_collection_raises_404_for_an_unlisted_collection(
    *, app_config: Settings, database: Database
) -> None:
    service = _service(app_config=app_config, database=database)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.get_collection(999, MediaType.MOVIE)
    assert exc_info.value.status_code == 404


async def test_set_collection_theme_enqueues_job(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _collection(db_session)
    downloads = FakeDownloads()
    service = _service(app_config=app_config, database=database, downloads=downloads)

    result = await service.set_collection_theme(
        1,
        SetCollectionThemeRequest(youtube_id="abcDEF123_4", media_type=MediaType.MOVIE),
    )

    assert result.job_id == "job-1"
    assert downloads.targets == [
        JobTarget.collection_theme(1, "Collection c1", "abcDEF123_4")
    ]


async def test_set_collection_theme_says_why_jellyfin_cannot_store_it(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _collection(db_session)
    service = _service(
        app_config=app_config,
        database=database,
        provider=JellyfinProvider(app_config=app_config),
    )

    with pytest.raises(PublicServiceError, match="JELLYFIN_COLLECTIONS_PATH"):
        await service.set_collection_theme(
            1,
            SetCollectionThemeRequest(youtube_id="a" * 11, media_type=MediaType.MOVIE),
        )


async def test_delete_collection_theme_clears_row_and_broadcasts(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _collection(db_session, youtube_id="abcDEF12345", server_theme_id="/t/1")
    provider = FakePlex(app_config=app_config)
    publisher = FakePublisher()
    service = _service(
        app_config=app_config,
        database=database,
        provider=provider,
        publisher=publisher,
    )

    result = await service.delete_collection_theme(1, MediaType.MOVIE)

    assert result.status is Status.OK
    assert provider.deleted_theme_for == ["c1"]
    row = await CollectionRepository(db_session).get(1, MediaType.MOVIE)
    assert row is not None
    await db_session.refresh(row)
    assert (row.youtube_id, row.server_theme_id) == (None, None)
    assert publisher.broadcasts[0][0] == "collection.theme.updated"
    assert publisher.broadcasts[0][1]["has_theme"] is False


async def test_delete_collection_theme_keeps_the_row_when_the_server_fails(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _collection(db_session, youtube_id="abcDEF12345", server_theme_id="/t/1")
    service = _service(
        app_config=app_config,
        database=database,
        provider=FakePlex(app_config=app_config, delete_error=MediaServerError("x")),
    )

    with pytest.raises(MediaServerError):
        await service.delete_collection_theme(1, MediaType.MOVIE)

    row = await CollectionRepository(db_session).get(1, MediaType.MOVIE)
    assert row is not None
    assert row.youtube_id == "abcDEF12345"


async def test_monitored_flags_change_only_listed_collections(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _collection(db_session, "c1")
    await _collection(db_session, "c2")
    service = _service(app_config=app_config, database=database)

    single = await service.set_collection_monitored(1, MediaType.MOVIE, False)
    bulk = await service.bulk_set_collection_monitored(
        [1, 2, 999], MediaType.MOVIE, False
    )

    assert single.monitored is False
    assert bulk.updated == 2
    with pytest.raises(PublicServiceError) as exc_info:
        await service.set_collection_monitored(999, MediaType.MOVIE, False)
    assert exc_info.value.status_code == 404


async def test_proxy_collection_image_has_no_season_posters(
    *, app_config: Settings, database: Database
) -> None:
    service = _service(app_config=app_config, database=database)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.proxy_collection_image(1, ArtType.SEASON_POSTER, None)
    assert exc_info.value.status_code == 404


async def test_proxy_collection_image_delegates_to_proxy_provider_image(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _collection(
        db_session, thumb_url="http://plex/library/collections/c1/composite/5"
    )
    provider = FakePlex(app_config=app_config)

    async def fake_proxy_provider_image(
        request: ProviderImageRequest, *, proxy_clients: ProxyClientManager
    ) -> Response:
        return Response("sentinel-response")

    monkeypatch.setattr(module, "proxy_provider_image", fake_proxy_provider_image)
    service = _service(app_config=app_config, database=database, provider=provider)

    result = await service.proxy_collection_image(1, ArtType.POSTER, ImageSize.DISPLAY)

    assert result.body == b"sentinel-response"
    assert provider.image_requests == [
        (
            "c1",
            ArtType.POSTER,
            ImageSize.DISPLAY,
            "http://plex/library/collections/c1/composite/5",
        )
    ]
    # Without a background sync saw, the server is not asked for one.
    with pytest.raises(PublicServiceError) as exc_info:
        await service.proxy_collection_image(1, ArtType.BACKGROUND, None)
    assert exc_info.value.status_code == 404
    assert len(provider.image_requests) == 1


async def test_jellyfin_detail_validates_the_mount_and_deleting_clears_file_facts(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    refreshed: list[str] = []

    class Jellyfin(JellyfinProvider):
        @override
        async def refresh_item(
            self, item_id: str, *, unlock: Collection[ServerAsset]
        ) -> None:
            refreshed.append(item_id)

    app_config.JELLYFIN_COLLECTIONS_PATH = tmp_path
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                id=1,
                server_item_id="opaque-id",
                server_type=ServerType.JELLYFIN,
                media_type=MediaType.MOVIE,
                server_path="/config/collections/Saga [boxset]",
                youtube_id="a" * 11,
                theme_file_hash="known",
                theme_file_size=5,
                last_synced_at=utc_now(),
            )
        )
    service = _service(
        app_config=app_config,
        database=database,
        provider=Jellyfin(app_config=app_config),
    )
    detail = await service.get_collection(1, MediaType.MOVIE)
    assert not detail.theme_writable
    assert detail.theme_unavailable is not None
    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    (folder / "theme.mp3").write_bytes(b"audio")
    assert (await service.get_collection(1, MediaType.MOVIE)).theme_writable
    await service.delete_collection_theme(1, MediaType.MOVIE)
    assert not (folder / "theme.mp3").exists()
    assert refreshed == ["opaque-id"]
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        assert row.youtube_id is None
        assert row.theme_file_hash is None
        assert row.theme_file_size is None
