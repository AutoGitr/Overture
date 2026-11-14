"""No API read gets more expensive per title as the library grows.

Every GET route in the OpenAPI document is measured, so a new route is covered
the moment it exists.
"""

lazy import re
lazy from typing import Any

lazy from fastapi import FastAPI
lazy from httpx2 import AsyncClient
lazy from sqlalchemy.ext.asyncio import AsyncEngine
lazy from sqlmodel import text

lazy from overture.db.models.art import ArtSlot
lazy from overture.db.models.media_collection import CollectionLibrary, MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, TermKind
lazy from overture.repositories.terms import TermRepository
lazy from overture.utils.time import utc_now
lazy from tests.workload import Workload, recording

_TITLES = 100
#: The statements any one read may take, whatever the library holds.
_MOST_STATEMENTS = 40

#: Reads that page through the library, a few statements per page.
_PAGED = {"/api/catalog/export"}
#: Reads that return every title or collection, with the entities each may build.
_LISTINGS = {
    "/api/collections": 3,
    "/api/library/items": 3,
    "/api/catalog/export": 3,
    "/api/stats": 3,
}

#: A value for each parameter routes take, so most reach their real work.
_VALUES = {
    "art_type": "poster",
    "collection_id": "10",
    "field": "actor",
    "item_id": "10",
    "library_id": "movies",
    "media_type": "movie",
    "query": "title",
    "season_id": "1",
}


async def _stock(database: Database, first: int, count: int) -> None:
    """Add titles with artwork and values, every tenth also in a collection."""
    span = range(first, first + count)
    async with database.write_session() as session:
        session.add_all(
            MediaItem(
                id=item_id,
                media_type=MediaType.SHOW if item_id % 4 == 0 else MediaType.MOVIE,
                title=f"Title {item_id}",
                tmdb_id=item_id,
                folder_path=f"/media/{item_id}",
                server_item_id=f"server-{item_id}",
                library_id="shows" if item_id % 4 == 0 else "movies",
            )
            for item_id in span
        )
        await session.flush()
        session.add_all(
            ArtSlot(
                media_item_id=item_id,
                art_type=ArtType.POSTER,
                file_hash="a" * 32,
                width=1000,
                height=1500,
            )
            for item_id in span
        )
        session.add_all(
            Season(media_item_id=item_id, season_num=1, file_count=3)
            for item_id in span
            if item_id % 4 == 0
        )
        now = utc_now()
        for item_id in span:
            if item_id % 10 == 0:
                collection = MediaCollection(
                    id=item_id,
                    title=f"Collection {item_id}",
                    last_synced_at=now,
                    created_at=now,
                )
                collection.libraries = [
                    CollectionLibrary(
                        collection_id=item_id,
                        library_id="movies",
                        media_type=MediaType.MOVIE,
                        server_item_id=f"collection-{item_id}",
                    )
                ]
                session.add(collection)
        await session.flush()
        await TermRepository(session).assign_many(
            {
                item_id: {TermKind.DIRECTOR: ["Director"], TermKind.GENRE: ["Drama"]}
                for item_id in span
                if item_id % 4
            }
        )


def _urls(app: FastAPI) -> dict[str, str]:
    """A concrete URL for every GET route, by its path template."""
    urls: dict[str, str] = {}
    for path, operations in app.openapi()["paths"].items():
        if "get" not in operations:
            continue
        parameters: list[dict[str, Any]] = operations["get"].get("parameters", [])
        query = "&".join(
            f"{parameter['name']}={_VALUES.get(parameter['name'], '1')}"
            for parameter in parameters
            if parameter["in"] == "query" and parameter.get("required")
        )
        filled = re.sub(r"{(\w+)[^}]*}", lambda found: _VALUES.get(found[1], "1"), path)
        urls[path] = f"{filled}?{query}" if query else filled
    return urls


async def _measure(
    client: AsyncClient, engine: AsyncEngine, urls: dict[str, str]
) -> dict[str, tuple[int, Workload]]:
    measured: dict[str, tuple[int, Workload]] = {}
    for path, url in urls.items():
        with recording(engine) as workload:
            response = await client.get(url)
        measured[path] = (response.status_code, workload)
    return measured


async def test_every_read_costs_the_same_at_twice_the_titles(
    async_client: AsyncClient,
    session_token: str,
    test_app: FastAPI,
    database: Database,
    isolated_engine: AsyncEngine,
) -> None:
    async_client.cookies.set("overture_token", session_token)
    async with isolated_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE libraries SET removed_at = NULL WHERE "
                "(id = 'movies' AND media_type = 'movie') "
                "OR (id = 'shows' AND media_type = 'show')"
            )
        )
    await _stock(database, 1, _TITLES)
    urls = _urls(test_app)

    small = await _measure(async_client, isolated_engine, urls)
    await _stock(database, _TITLES + 1, _TITLES)
    large = await _measure(async_client, isolated_engine, urls)

    grew: dict[str, tuple[int, ...]] = {}
    for path, (status, before) in small.items():
        _, after = large[path]
        statements = (len(before.statements), len(after.statements))
        entities = (before.entities.total(), after.entities.total())
        allowed = _LISTINGS.get(path, 0) * _TITLES
        if (
            statements[1] > _MOST_STATEMENTS
            or (statements[0] != statements[1] and path not in _PAGED)
            or entities[1] - entities[0] > allowed
        ):
            grew[path] = (status, *statements, *entities)
    assert not grew
