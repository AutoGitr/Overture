"""Catalog router sync statuses."""

lazy from typing import override

lazy from fastapi.testclient import TestClient

lazy from overture.config import Settings
lazy from overture.db.models.catalog import (
    CatalogCollection,
    CatalogItem,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import MediaType
lazy from overture.routers import catalog
lazy from overture.schemas.catalog import CatalogStatus
lazy from overture.schemas.common import Status
lazy from tests.bulk_helpers import enable_catalog
lazy from tests.collection_helpers import stored_collection
lazy from tests.runtime_helpers import (
    NoopCatalog,
)


async def test_catalog_sync_route_handles_disabled_started_and_running(
    app_config: Settings,
) -> None:
    class Catalog(NoopCatalog):
        enabled = False
        started = True

        @override
        async def get_status(self) -> CatalogStatus:
            return self._noop_status(enabled=self.enabled)

        @override
        def start_background_sync(self) -> bool:
            return self.started

    service = Catalog(app_config=app_config)
    assert (await catalog.sync_catalog_now(service)).status == Status.DISABLED

    service.enabled = True
    assert (await catalog.sync_catalog_now(service)).status == Status.STARTED

    service.started = False
    assert (await catalog.sync_catalog_now(service)).status == Status.ALREADY_RUNNING


async def test_records_for_collections_and_catalog_entries(
    authenticated_client: TestClient, database: Database
) -> None:
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=4,
                server_item_id="saga",
                media_type=MediaType.MOVIE,
                title="Saga",
                tmdb_collection_id=10,
            )
        )
        session.add(CatalogCollection(tmdb_id=10, title="Saga Collection"))
        session.add(CatalogItem(media_type=MediaType.SHOW, tvdb_id=77, title="Show"))
        session.add(
            MediaItem(id=5, media_type=MediaType.SHOW, title="Show", tvdb_id=77)
        )
        await enable_catalog(session)

    collection = authenticated_client.get("/api/catalog/collections/4/record")
    entry = authenticated_client.get("/api/catalog/catalog/collection/tmdb-10/record")
    show = authenticated_client.get("/api/catalog/catalog/show/tvdb-77/record")
    missing = authenticated_client.get("/api/catalog/catalog/movie/tmdb-999/record")

    assert collection.json()["collection"]["title"] == "Saga Collection"
    assert entry.json() == collection.json()
    assert show.json()["item"]["title"] == "Show"
    sources = authenticated_client.get("/api/catalog/items/5/sources")
    # Drafts of the entry are saved under the name sources report.
    assert sources.json()["item"]["entry_key"] == "tvdb-77"
    assert missing.json() == {
        "found": False,
        "item": None,
        "collection": None,
        "seasons": [],
    }
