"""The test media server, and titles it holds."""

lazy from collections.abc import Sequence
lazy from datetime import UTC, datetime
lazy from typing import Any

lazy from pydantic import SecretStr
lazy from sqlalchemy.ext.asyncio import AsyncConnection
lazy from sqlmodel import col, insert, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import MediaServerConfig, Settings
lazy from overture.db.models.library import Library
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.media_item_copy import MediaItemCopy
lazy from overture.db.models.media_server import MediaServer
lazy from overture.domain import MediaType, ServerType, library_id, library_parts
lazy from overture.media_servers.registry import ProviderRegistry

#: The database's number of the test media server.
TEST_SERVER_ID = 1

#: The media server the test configuration names (``MEDIA_SERVERS=Plex``).
TEST_SERVER = MediaServerConfig(
    name="Plex",
    type=ServerType.PLEX,
    url="http://127.0.0.1:32400",
    api_key=SecretStr("x" * 32),
)

#: The fields a server keeps for its own copy of a title, by the copy's name.
_COPY_FIELDS = {
    "server_item_id": "server_item_id",
    "library_id": "library_id",
    "server_verified_at": "verified_at",
    "director_etag": "director_etag",
}


def served_item(**fields: Any) -> MediaItem:
    """Build a title with its copy on the server *library_id* names.

    ``server_item_id`` names the copy, in the test server's library ``1:1``
    unless ``library_id`` names another; a title without it has none, like one
    chosen from TMDB alone. The copy also takes the title's play state,
    rating, added time and removal.
    """
    copy = {
        name: fields.pop(field)
        for field, name in _COPY_FIELDS.items()
        if field in fields
    }
    item = MediaItem(**fields)
    if copy.get("server_item_id") is None:
        return item
    copy["library_id"] = copy.get("library_id") or f"{TEST_SERVER_ID}:1"
    parts = library_parts(copy["library_id"])
    item.copies = [
        MediaItemCopy(
            server_id=parts[0] if parts else TEST_SERVER_ID,
            media_type=MediaType(item.media_type),
            added_at=item.server_added_at,
            removed_at=item.server_removed_at,
            plays=item.plays,
            last_played_at=item.last_played_at,
            unplayed=item.unplayed,
            in_progress=item.in_progress,
            user_rating=item.user_rating,
            **copy,
        )
    ]
    return item


def configure(app_config: Settings, **changes: Any) -> MediaServerConfig:
    """Change the one server *app_config* names, as its variables would.

    A changed ``type`` also renames the server after its kind.
    """
    current = server_of(app_config)
    if "type" in changes:
        changes["name"] = ServerType(changes["type"]).display_name
    server = MediaServerConfig.model_validate({**current.model_dump(), **changes})
    app_config.MEDIA_SERVERS = (server,)
    return server


def server_of(
    app_config: Settings, server_type: ServerType | None = None
) -> MediaServerConfig:
    """Return the server *app_config* names, as a server of *server_type* if given."""
    server = app_config.MEDIA_SERVERS[0] if app_config.MEDIA_SERVERS else TEST_SERVER
    if server_type is None or server.type is server_type:
        return server
    return server.model_copy(
        update={"type": server_type, "name": server_type.display_name}
    )


def attached_registry(app_config: Settings) -> ProviderRegistry:
    """A registry of *app_config*'s servers, numbered as the test database numbers them.

    The roster attaches the registry when Overture starts; this stands in for it.
    """
    registry = ProviderRegistry(app_config=app_config)
    attach_servers(registry, app_config)
    return registry


async def copy_ids(session: AsyncSession) -> dict[int, str]:
    """Each title's ID on the test server, by title, as its copy records it."""
    rows = await session.exec(
        select(MediaItemCopy.media_item_id, MediaItemCopy.server_item_id).where(
            col(MediaItemCopy.server_id) == TEST_SERVER_ID
        )
    )
    return dict(rows.all())


def media_client(
    client_type: type[Any],
    app_config: Settings,
    **options: Any,
) -> Any:
    """Build a Plex, Jellyfin or Emby client for the server *app_config* names."""
    kinds = {"PlexClient": ServerType.PLEX, "EmbyClient": ServerType.EMBY}
    server = server_of(app_config, kinds.get(client_type.__name__, ServerType.JELLYFIN))
    if client_type.__name__ == "PlexClient":
        return client_type(server=server, app_config=app_config, **options)
    return client_type(server=server, **options)


async def seed_test_server(
    connection: AsyncConnection, library_keys: Sequence[str]
) -> None:
    """Record the test server and libraries of both types under *library_keys*.

    A sync once listed them; none is listed now, until a test records its
    provider's sections as a sync does.
    """
    await connection.execute(
        insert(MediaServer),
        [
            {
                "id": TEST_SERVER_ID,
                "key": TEST_SERVER.key,
                "title": TEST_SERVER.title,
                "server_type": TEST_SERVER.type,
                "identity": TEST_SERVER.identity,
                "position": 0,
            }
        ],
    )
    if not library_keys:
        return
    await connection.execute(
        insert(Library),
        [
            {
                "id": library_id(TEST_SERVER_ID, key),
                "media_type": media_type,
                "server_id": TEST_SERVER_ID,
                "title": key,
                "removed_at": datetime(2020, 1, 1, tzinfo=UTC),
            }
            for key in library_keys
            for media_type in MediaType
        ],
    )


def attach_servers(registry: ProviderRegistry, app_config: Settings) -> None:
    """Number *app_config*'s servers as the test database does, as the roster would."""
    registry.attach(
        {
            server.key: index
            for index, server in enumerate(
                app_config.MEDIA_SERVERS, start=TEST_SERVER_ID
            )
        }
    )
