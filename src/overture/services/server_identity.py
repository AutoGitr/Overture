"""Find the media servers' IDs of titles and seasons, outside transactions."""

lazy from dataclasses import dataclass

lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..db.session import Database
lazy from ..domain import ArtType
lazy from ..media_servers.registry import Provider, ProviderRegistry
lazy from ..repositories.copies import CopyRepository
lazy from ..repositories.seasons import SeasonRepository


@dataclass(slots=True, frozen=True)
class ServerCopy:
    """One configured server's ID of a title, or of one of its seasons."""

    provider: Provider
    server_item_id: str


async def resolve_art_owners(
    item_id: int,
    art_type: ArtType,
    season_id: int | None,
    *,
    database: Database,
    provider_registry: ProviderRegistry,
) -> list[ServerCopy]:
    """Return each server's ID of the item or season owning an art slot.

    See :func:`resolve_owners`.
    """
    return await resolve_owners(
        item_id,
        season_id if art_type.owned_by_season else None,
        database=database,
        provider_registry=provider_registry,
    )


async def resolve_owners(
    item_id: int,
    season_id: int | None,
    *,
    database: Database,
    provider_registry: ProviderRegistry,
    lead_only: bool = False,
    discover: bool = True,
) -> list[ServerCopy]:
    """Return every configured server's ID of a title or season, the lead first.

    A server lists a title's copy, and its sync records it, so only a
    season's ID may need asking the server for; it is saved in a short
    transaction of its own, unless a sync recorded one meanwhile. A title no
    sync has found on any server is looked up on each by its IDs, unless
    *discover* is false.
    """
    order = provider_registry.server_ids()
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        if item is None:
            return []
        copies = await CopyRepository(session).leads_first(item_id, order)
        season = (
            None
            if season_id is None
            else await SeasonRepository(session).get_for_item(season_id, item_id)
        )
        if season_id is not None and season is None:
            return []
        known = (
            {}
            if season is None
            else await CopyRepository(session).season_copies(season.id or 0)
        )
    if not copies:
        if not discover:
            return []
        return await _discovered(item, season, provider_registry, lead_only=lead_only)
    owners: list[ServerCopy] = []
    for copy in copies[:1] if lead_only else copies:
        provider = provider_registry.get(copy.server_id)
        if season is None:
            owners.append(ServerCopy(provider, copy.server_item_id))
            continue
        found = known.get(copy.server_id) or await provider.find_season_id(
            copy.server_item_id, season.season_num
        )
        if found is None:
            continue
        if copy.server_id not in known:
            async with database.write_session() as session:
                found = await CopyRepository(session).keep_season_id(
                    season.id or 0, copy.server_id, found
                )
            if found is None:
                return []
        owners.append(ServerCopy(provider, found))
    return owners


async def _discovered(
    item: MediaItem,
    season: Season | None,
    provider_registry: ProviderRegistry,
    *,
    lead_only: bool,
) -> list[ServerCopy]:
    """Ask each server for a title no sync has found on any, by its IDs.

    What a server answers is not kept: its next sync records the copy, in the
    library that holds it.
    """
    owners: list[ServerCopy] = []
    for provider in provider_registry.providers():
        found = await provider.find_item_id(item)
        if found and season is not None:
            found = await provider.find_season_id(found, season.season_num)
        if found:
            owners.append(ServerCopy(provider, found))
            if lead_only:
                break
    return owners


async def resolve_lead_owner(
    item_id: int,
    art_type: ArtType,
    season_id: int | None,
    *,
    database: Database,
    provider_registry: ProviderRegistry,
    discover: bool = True,
) -> ServerCopy | None:
    """Return the lead server's ID of the item or season owning an art slot."""
    owners = await resolve_owners(
        item_id,
        season_id if art_type.owned_by_season else None,
        database=database,
        provider_registry=provider_registry,
        lead_only=True,
        discover=discover,
    )
    return next(iter(owners), None)
