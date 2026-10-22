"""Coverage for collection listing, theme, monitoring, and image-proxy actions."""

lazy from datetime import UTC, datetime
lazy from typing import Any, override

lazy import pytest
lazy from fastapi.responses import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    ImageSize,
    MediaType,
    ServerType,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.media_servers.adapters import ProviderImageRequest
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.repositories.collection_themes import CollectionThemeRepository
lazy from overture.schemas.collections import SetCollectionThemeRequest
lazy from overture.schemas.common import Status
lazy from overture.services.collections import service as module
lazy from overture.services.downloads.queue import AssetScope, JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.locks import KeyedLock
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    database_for,
    one_session,
    unused,
)

TS = datetime(2026, 1, 1, tzinfo=UTC)


class FakeProvider:
    """The collection surface of a Plex provider, recording what it was asked."""

    server_type = ServerType.PLEX

    def __init__(
        self,
        *,
        collections: list[dict[str, Any]] | None = None,
        list_collections_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self._collections = collections or []
        self._list_error = list_collections_error
        self._delete_error = delete_error
        self.deleted_theme_for: list[str] = []
        self.image_requests: list[tuple[str, ArtType, ImageSize | None]] = []

    async def list_collections(self, media_type: MediaType) -> list[dict[str, Any]]:
        if self._list_error:
            raise self._list_error
        return [
            {"media_type": media_type, "server_type": self.server_type, **collection}
            for collection in self._collections
        ]

    async def delete_collection_theme(self, server_item_id: str) -> None:
        if self._delete_error:
            raise self._delete_error
        self.deleted_theme_for.append(server_item_id)

    async def build_collection_image_request(
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
    ) -> ProviderImageRequest:
        self.image_requests.append((server_item_id, art_type, size))
        return ProviderImageRequest(url="https://example.test/img", headers={})


def _service(
    *,
    database: Database,
    provider: FakeProvider | None = None,
    plex: bool = True,
    publisher: Any | None = None,
    downloads: DownloadService | None = None,
    proxy_clients: Any | None = None,
) -> module.CollectionsService:
    return module.CollectionsService(
        database=database,
        provider_registry=NoopProviderRegistry(
            provider or FakeProvider(), collections=plex
        ),
        publisher=publisher or FakePublisher(),
        downloads=downloads or FakeDownloads(),
        proxy_clients=proxy_clients or unused(ProxyClientManager),
    )


class FakeDownloads(DownloadService):
    """Records the targets queued."""

    def __init__(self, *, job_id: str = "job-1") -> None:
        self._job_id = job_id
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
        return self._job_id, True

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
        built = builder()
        if built is None:
            return False
        event, payload = built
        self.broadcasts.append((event, payload))
        return True


# --- require_collection ------------------------------------------------------------


async def test_require_collection_rejects_a_server_without_collections(
    database: Database,
) -> None:
    service = _service(database=database, plex=False)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.require_collection("c1", MediaType.MOVIE)
    assert exc_info.value.status_code == 400


async def test_require_collection_returns_the_matching_collection(
    database: Database,
) -> None:
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    service = _service(database=database, provider=provider)
    result = await service.require_collection("c1", MediaType.MOVIE)
    assert result["title"] == "Marvel"


async def test_require_collection_raises_404_when_not_found(
    database: Database,
) -> None:
    provider = FakeProvider(collections=[{"id": "other", "title": "X"}])
    service = _service(database=database, provider=provider)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.require_collection("c1", MediaType.MOVIE)
    assert exc_info.value.status_code == 404


async def test_require_collection_propagates_provider_failure(
    database: Database,
) -> None:
    provider = FakeProvider(
        list_collections_error=MediaServerError("Unavailable", status_code=503)
    )
    service = _service(database=database, provider=provider)
    with pytest.raises(MediaServerError) as exc_info:
        await service.require_collection("c1", MediaType.MOVIE)
    assert exc_info.value.status_code == 503


# --- list_collections --------------------------------------------------------------


async def test_list_collections_rejects_a_server_without_collections(
    database: Database,
) -> None:
    service = _service(database=database, plex=False)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.list_collections(MediaType.MOVIE)
    assert exc_info.value.status_code == 400


async def test_list_collections_returns_empty_when_provider_has_none(
    database: Database,
) -> None:
    service = _service(database=database, provider=FakeProvider(collections=[]))
    assert await service.list_collections(MediaType.MOVIE) == []


async def _uploaded_theme(
    session: AsyncSession,
    server_item_id: str,
    *,
    title: str,
    server_theme_id: str,
) -> None:
    await CollectionThemeRepository(session).upsert_uploaded_theme(
        server_item_id=server_item_id,
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        youtube_id="dQw4w9WgXcQ",
        youtube_title=title,
        youtube_duration=120,
        server_theme_id=server_theme_id,
        timestamp=TS,
    )
    await session.commit()


async def test_list_collections_merges_matching_theme_provenance(
    db_session: AsyncSession, database: Database
) -> None:
    await _uploaded_theme(
        db_session, "c1", title="Marvel Theme", server_theme_id="/themes/marvel"
    )
    provider = FakeProvider(
        collections=[
            {"id": "c1", "title": "Marvel", "theme_id": "/themes/marvel"},
            {"id": "c2", "title": "DC"},
        ]
    )
    result = await _service(database=database, provider=provider).list_collections(
        MediaType.MOVIE
    )

    by_id = {c.id: c for c in result}
    assert by_id["c1"].has_theme is True
    assert by_id["c1"].youtube_id == "dQw4w9WgXcQ"
    assert by_id["c1"].youtube_title == "Marvel Theme"
    assert by_id["c1"].youtube_duration == 120
    assert by_id["c2"].has_theme is False
    assert by_id["c2"].monitored is True  # default when no local row exists


async def test_list_collections_invalidates_provenance_for_external_theme_change(
    db_session: AsyncSession, database: Database
) -> None:
    await _uploaded_theme(
        db_session, "c1", title="Old Theme", server_theme_id="/themes/old"
    )
    provider = FakeProvider(
        collections=[{"id": "c1", "title": "Marvel", "theme_id": "/themes/replaced"}]
    )
    result = await _service(database=database, provider=provider).list_collections(
        MediaType.MOVIE
    )

    assert result[0].has_theme is True
    assert result[0].youtube_id is None
    assert result[0].youtube_title is None
    assert result[0].youtube_duration is None
    row = await CollectionThemeRepository(db_session).get_for_collection(
        "c1", MediaType.MOVIE
    )
    assert row is not None
    await db_session.refresh(row)
    assert row.server_theme_id == "/themes/replaced"


async def test_list_collections_invalidates_provenance_for_external_theme_removal(
    db_session: AsyncSession, database: Database
) -> None:
    await _uploaded_theme(
        db_session, "c1", title="Removed Theme", server_theme_id="/themes/removed"
    )
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    result = await _service(database=database, provider=provider).list_collections(
        MediaType.MOVIE
    )

    assert result[0].has_theme is False
    assert result[0].youtube_id is None
    row = await CollectionThemeRepository(db_session).get_for_collection(
        "c1", MediaType.MOVIE
    )
    assert row is not None
    await db_session.refresh(row)
    assert row.server_theme_id is None
    assert row.youtube_title is None
    assert row.youtube_duration is None


async def test_list_collections_invalidates_removed_collection_provenance(
    db_session: AsyncSession, database: Database
) -> None:
    await _uploaded_theme(
        db_session,
        "removed",
        title="Removed Collection Theme",
        server_theme_id="/themes/removed-collection",
    )
    result = await _service(
        database=database, provider=FakeProvider(collections=[])
    ).list_collections(MediaType.MOVIE)

    assert result == []
    row = await CollectionThemeRepository(db_session).get_for_collection(
        "removed", MediaType.MOVIE
    )
    assert row is not None
    await db_session.refresh(row)
    assert row.server_theme_id is None
    assert row.youtube_id is None
    assert row.youtube_title is None
    assert row.youtube_duration is None


# --- get_collection_theme -----------------------------------------------------------


async def test_get_collection_theme_rejects_a_server_without_collections(
    database: Database,
) -> None:
    service = _service(database=database, plex=False)
    with pytest.raises(PublicServiceError):
        await service.get_collection_theme("c1", MediaType.MOVIE)


async def test_get_collection_theme_returns_live_provider_state_without_a_row(
    database: Database,
) -> None:
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    service = _service(database=database, provider=provider)
    status = await service.get_collection_theme("c1", MediaType.MOVIE)
    assert status.has_theme is False


# --- set_collection_theme -----------------------------------------------------------

_THEME = SetCollectionThemeRequest(youtube_id="dQw4w9WgXcQ", media_type=MediaType.MOVIE)


async def test_set_collection_theme_enqueues_job(database: Database) -> None:
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    downloads = FakeDownloads(job_id="job-42")
    service = _service(database=database, provider=provider, downloads=downloads)

    result = await service.set_collection_theme("c1", _THEME)

    assert result.job_id == "job-42"
    assert result.status == Status.ENQUEUED
    assert downloads.targets == [
        JobTarget.collection_theme("c1", MediaType.MOVIE, "Marvel", "dQw4w9WgXcQ")
    ]


# --- delete_collection_theme ---------------------------------------------------------


async def test_delete_collection_theme_clears_row_and_broadcasts(
    db_session: AsyncSession,
) -> None:
    await _uploaded_theme(
        db_session, "c1", title="Marvel Theme", server_theme_id="/themes/marvel"
    )
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    publisher = FakePublisher()
    service = _service(
        database=database_for(one_session(db_session)),
        provider=provider,
        publisher=publisher,
    )

    result = await service.delete_collection_theme("c1", MediaType.MOVIE)

    assert result.status == Status.OK
    assert result.has_theme is False
    assert provider.deleted_theme_for == ["c1"]
    assert publisher.broadcasts[0][0] == "collection.theme.updated"
    row = await CollectionThemeRepository(db_session).get_for_collection(
        "c1", MediaType.MOVIE
    )
    assert row is not None
    assert row.youtube_id is None


async def test_delete_collection_theme_keeps_the_row_when_the_server_fails(
    db_session: AsyncSession,
) -> None:
    await _uploaded_theme(
        db_session, "c1", title="Marvel Theme", server_theme_id="/themes/marvel"
    )
    provider = FakeProvider(
        collections=[{"id": "c1", "title": "Marvel"}],
        delete_error=MediaServerError("Plex refused"),
    )
    publisher = FakePublisher()
    service = _service(
        database=database_for(one_session(db_session)),
        provider=provider,
        publisher=publisher,
    )

    with pytest.raises(MediaServerError):
        await service.delete_collection_theme("c1", MediaType.MOVIE)

    assert publisher.broadcasts == []
    row = await CollectionThemeRepository(db_session).get_for_collection(
        "c1", MediaType.MOVIE
    )
    assert row is not None
    assert row.youtube_id == "dQw4w9WgXcQ"


# --- monitoring -----------------------------------------------------------------------


@pytest.mark.parametrize("monitored", [True, False])
async def test_set_collection_monitored_creates_the_row(
    db_session: AsyncSession, *, monitored: bool
) -> None:
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    service = _service(
        database=database_for(one_session(db_session)), provider=provider
    )

    result = await service.set_collection_monitored("c1", MediaType.MOVIE, monitored)

    assert result.monitored is monitored
    row = await CollectionThemeRepository(db_session).get_for_collection(
        "c1", MediaType.MOVIE
    )
    assert row is not None
    assert row.monitored is monitored


async def test_set_collection_monitored_is_idempotent(
    db_session: AsyncSession,
) -> None:
    await CollectionThemeRepository(db_session).set_monitored(
        server_item_id="c1",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        monitored=False,
        timestamp=TS,
    )
    await db_session.commit()
    provider = FakeProvider(collections=[{"id": "c1", "title": "Marvel"}])
    service = _service(
        database=database_for(one_session(db_session)), provider=provider
    )

    first = await service.set_collection_monitored("c1", MediaType.MOVIE, False)
    second = await service.set_collection_monitored("c1", MediaType.MOVIE, False)

    assert first.monitored is second.monitored is False


async def test_bulk_set_collection_monitored(db_session: AsyncSession) -> None:
    provider = FakeProvider(
        collections=[{"id": "c1", "title": "Marvel"}, {"id": "c2", "title": "DC"}]
    )
    service = _service(
        database=database_for(one_session(db_session)), provider=provider
    )

    res = await service.bulk_set_collection_monitored(
        ["c1", "c2"], MediaType.MOVIE, False
    )
    assert res.updated == 2

    repo = CollectionThemeRepository(db_session)
    for server_id in ("c1", "c2"):
        row = await repo.get_for_collection(server_id, MediaType.MOVIE)
        assert row is not None
        assert row.monitored is False


# --- proxy_collection_image ---------------------------------------------------------


async def test_proxy_collection_image_has_no_season_posters(
    database: Database,
) -> None:
    service = _service(database=database)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.proxy_collection_image("c1", ArtType.SEASON_POSTER, None)
    assert exc_info.value.status_code == 404


async def test_proxy_collection_image_rejects_a_server_without_collections(
    database: Database,
) -> None:
    service = _service(database=database, plex=False)
    with pytest.raises(PublicServiceError) as exc_info:
        await service.proxy_collection_image("c1", ArtType.POSTER, None)
    assert exc_info.value.status_code == 400


async def test_proxy_collection_image_delegates_to_proxy_provider_image(
    monkeypatch: pytest.MonkeyPatch, database: Database
) -> None:
    provider = FakeProvider()

    async def fake_proxy_provider_image(
        request: ProviderImageRequest, *, proxy_clients: ProxyClientManager
    ) -> Response:
        return Response("sentinel-response")

    monkeypatch.setattr(module, "proxy_provider_image", fake_proxy_provider_image)

    service = _service(database=database, provider=provider)
    result = await service.proxy_collection_image(
        "c1", ArtType.POSTER, ImageSize.DISPLAY
    )

    assert result.body == b"sentinel-response"
    assert provider.image_requests == [("c1", ArtType.POSTER, ImageSize.DISPLAY)]
