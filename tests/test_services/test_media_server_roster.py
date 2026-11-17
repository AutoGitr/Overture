"""The configured media servers keep their rows across restarts."""

lazy from pydantic import SecretStr
lazy from sqlmodel import select

lazy from overture.config import MediaServerConfig, Settings
lazy from overture.db.models.library import Library
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.media_item_copy import MediaItemCopy
lazy from overture.db.models.media_server import MediaServer
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerType
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.repositories.copies import CopyRepository
lazy from overture.services.media_server_roster import MediaServerRoster
lazy from tests.media_servers import TEST_SERVER, TEST_SERVER_ID

JELLYFIN = MediaServerConfig(
    name="Jellyfin",
    type=ServerType.JELLYFIN,
    url="http://jellyfin.test:8096",
    api_key=SecretStr("jellyfin-key"),
)


async def _start(
    app_config: Settings, database: Database, *servers: MediaServerConfig
) -> list[int]:
    """Start Overture with *servers* in MEDIA_SERVERS; return their numbers."""
    app_config.MEDIA_SERVERS = servers
    registry = ProviderRegistry(app_config=app_config)
    await MediaServerRoster(database=database, provider_registry=registry).reconcile()
    return registry.server_ids()


async def _rows(database: Database) -> dict[int, MediaServer]:
    async with database.read_session() as session:
        rows = (await session.exec(select(MediaServer))).all()
    return {row.id or 0: row for row in rows}


async def _hold(database: Database, item_id: int, *server_ids: int) -> None:
    """Store a title each of *server_ids* lists in its movie library."""
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=item_id,
                media_type=MediaType.MOVIE,
                title=f"Title {item_id}",
                tmdb_id=item_id,
            )
        )
        for server_id in server_ids:
            library = await session.get(
                Library, (f"{server_id}:1", MediaType.MOVIE)
            ) or Library(
                id=f"{server_id}:1",
                media_type=MediaType.MOVIE,
                server_id=server_id,
                title="Movies",
            )
            library.removed_at = None
            session.add(library)
            session.add(
                MediaItemCopy(
                    media_item_id=item_id,
                    server_id=server_id,
                    media_type=MediaType.MOVIE,
                    server_item_id=f"{server_id}-{item_id}",
                    library_id=f"{server_id}:1",
                )
            )


async def _visible(database: Database, item_id: int) -> bool:
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
    assert item is not None
    return item.server_removed_at is None


async def test_servers_keep_their_rows_and_take_their_place_in_order(
    app_config: Settings, database: Database
) -> None:
    plex_id, jellyfin_id = await _start(app_config, database, TEST_SERVER, JELLYFIN)
    assert plex_id == TEST_SERVER_ID
    rows = await _rows(database)
    assert (rows[plex_id].position, rows[jellyfin_id].position) == (0, 1)
    await _hold(database, 1, jellyfin_id, plex_id)

    # Reordered and renamed, each is still the server at its address.
    renamed = JELLYFIN.model_copy(update={"name": "Living_Room"})
    assert await _start(app_config, database, renamed, TEST_SERVER) == [
        jellyfin_id,
        plex_id,
    ]
    rows = await _rows(database)
    assert (rows[jellyfin_id].key, rows[jellyfin_id].title) == (
        "living_room",
        "Living Room",
    )
    assert (rows[jellyfin_id].position, rows[plex_id].position) == (0, 1)
    # A title's copies are listed lead first, in the new order.
    async with database.read_session() as session:
        copies = await CopyRepository(session).leads_first(1)
    assert [copy.server_id for copy in copies] == [jellyfin_id, plex_id]


async def test_a_server_that_leaves_hides_what_only_it_held_until_it_returns(
    app_config: Settings, database: Database
) -> None:
    plex_id, jellyfin_id = await _start(app_config, database, TEST_SERVER, JELLYFIN)
    await _hold(database, 1, plex_id, jellyfin_id)
    await _hold(database, 2, jellyfin_id)

    assert await _start(app_config, database, TEST_SERVER) == [plex_id]
    rows = await _rows(database)
    assert rows[jellyfin_id].removed_at is not None
    assert rows[jellyfin_id].position is None
    assert await _visible(database, 1)
    assert not await _visible(database, 2)
    async with database.read_session() as session:
        copies = await CopyRepository(session).leads_first(1)
    assert [copy.server_id for copy in copies] == [plex_id]

    # Back at its address, it takes up its row and what it held.
    assert await _start(app_config, database, TEST_SERVER, JELLYFIN) == [
        plex_id,
        jellyfin_id,
    ]
    async with database.write_session() as session:
        library = await session.get(Library, (f"{jellyfin_id}:1", MediaType.MOVIE))
        assert library is not None
        # Its next sync lists the library again.
        library.removed_at = None
        session.add(library)
    await _start(app_config, database, TEST_SERVER, JELLYFIN)
    assert await _visible(database, 2)
