"""Discover provider identifiers outside application database transactions."""

lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..db.session import Database
lazy from ..domain import ArtType
lazy from ..media_servers.registry import ProviderRegistry
lazy from ..repositories.seasons import SeasonRepository
lazy from ..utils.time import utc_now


async def resolve_server_item_id(
    item_id: int,
    art_type: ArtType,
    season_id: int | None,
    *,
    database: Database,
    provider_registry: ProviderRegistry,
) -> str | None:
    """Return the media-server ID of the item or season owning an art slot.

    See :func:`resolve_owner_server_id`.
    """
    return await resolve_owner_server_id(
        item_id,
        season_id if art_type.owned_by_season else None,
        database=database,
        provider_registry=provider_registry,
    )


async def resolve_owner_server_id(
    item_id: int,
    season_id: int | None,
    *,
    database: Database,
    provider_registry: ProviderRegistry,
) -> str | None:
    """Read identity, discover remotely, then persist in a short owned transaction.

    Re-read before writing so concurrent discovery cannot overwrite an identifier
    saved by sync, or resurrect an item deleted while the provider was responding.
    """
    provider = provider_registry.provider
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        if item is None:
            return None
        target = (
            item
            if season_id is None
            else await SeasonRepository(session).get_for_item(season_id, item_id)
        )
        if target is None:
            return None
        if target.server_item_id:
            return target.server_item_id
    season = target if isinstance(target, Season) else None

    parent_id = item.server_item_id or await provider.find_item_id(item)
    if not parent_id:
        return None
    link = (
        await provider.build_item_link(parent_id) if not item.server_item_id else None
    )
    server_id = (
        await provider.find_season_id(parent_id, season.season_num)
        if season is not None
        else parent_id
    )

    return await _save_identity(
        item_id, parent_id, link, season, server_id, database=database
    )


async def _save_identity(
    item_id: int,
    parent_id: str,
    link: str | None,
    season: Season | None,
    server_id: str | None,
    *,
    database: Database,
) -> str | None:
    """Persist discovery without overwriting a newer sync result."""
    async with database.write_session() as session:
        current = await session.get(MediaItem, item_id)
        if current is None:
            return None
        if current.server_item_id and current.server_item_id != parent_id:
            # A newer sync changed the parent; the discovered season is stale.
            return current.server_item_id if season is None else None
        if not current.server_item_id:
            current.server_item_id = parent_id
            current.server_verified_at = utc_now()
            current.server_link = link
        if season is None:
            return current.server_item_id
        if season.id is None:
            raise ValueError("Season ID must not be None")
        current_season = await SeasonRepository(session).get_for_item(
            season.id, item_id
        )
        if current_season is None or current_season.season_num != season.season_num:
            return None
        if not current_season.server_item_id:
            current_season.server_item_id = server_id
        return current_season.server_item_id
