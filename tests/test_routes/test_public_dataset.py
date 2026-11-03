"""Public dataset router sync statuses."""

lazy from typing import override

lazy from fastapi.testclient import TestClient

lazy from overture.config import Settings
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import (
    PublicDatasetCollection,
    PublicDatasetItem,
)
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerType
lazy from overture.routers import public_dataset
lazy from overture.schemas.common import Status
lazy from overture.schemas.public_dataset import PublicDatasetStatus
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.runtime_helpers import (
    NoopPublicDataset,
)


async def test_public_dataset_sync_route_handles_disabled_started_and_running(
    app_config: Settings,
) -> None:
    class PublicDataset(NoopPublicDataset):
        enabled = False
        started = True

        @override
        async def get_status(self) -> PublicDatasetStatus:
            return self._noop_status(enabled=self.enabled)

        @override
        def start_background_sync(self) -> bool:
            return self.started

    service = PublicDataset(app_config=app_config)
    assert (
        await public_dataset.sync_public_dataset_now(service)
    ).status == Status.DISABLED

    service.enabled = True
    assert (
        await public_dataset.sync_public_dataset_now(service)
    ).status == Status.STARTED

    service.started = False
    assert (
        await public_dataset.sync_public_dataset_now(service)
    ).status == Status.ALREADY_RUNNING


async def test_records_for_collections_and_catalog_entries(
    authenticated_client: TestClient, database: Database
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                id=4,
                server_item_id="saga",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                title="Saga",
                tmdb_collection_id=10,
            )
        )
        session.add(PublicDatasetCollection(tmdb_id=10, title="Saga Collection"))
        session.add(
            PublicDatasetItem(media_type=MediaType.SHOW, tvdb_id=77, title="Show")
        )
        session.add(
            MediaItem(id=5, media_type=MediaType.SHOW, title="Show", tvdb_id=77)
        )
        await enable_public_dataset(session)

    collection = authenticated_client.get("/api/public-dataset/collections/4/record")
    entry = authenticated_client.get(
        "/api/public-dataset/catalog/collection/tmdb-10/record"
    )
    show = authenticated_client.get("/api/public-dataset/catalog/show/tvdb-77/record")
    missing = authenticated_client.get(
        "/api/public-dataset/catalog/movie/tmdb-999/record"
    )

    assert collection.json()["collection"]["title"] == "Saga Collection"
    assert entry.json() == collection.json()
    assert show.json()["item"]["title"] == "Show"
    sources = authenticated_client.get("/api/public-dataset/items/5/sources")
    # Drafts of the entry are saved under the name sources report.
    assert sources.json()["item"]["entry_key"] == "tvdb-77"
    assert missing.json() == {
        "found": False,
        "item": None,
        "collection": None,
        "seasons": [],
    }
