"""Provider artwork URL reconciliation helpers.

Copies safe, publicly reachable poster/background URLs from a media-server
provider snapshot onto local ``MediaItem``/``Season`` records, without ever
overwriting a value the app has already resolved unless explicitly allowed.
"""

lazy from collections.abc import Iterable, Mapping

lazy from ...config import Settings
lazy from ...db.art_slots import read_art_slot, select_art
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType
lazy from ...media_servers.adapters import ServerItem
lazy from ...utils.art_urls import public_art_url

#: Provider artwork URLs mapped to the public form they resolved to.
type ResolvedArtUrls = Mapping[str, str]


async def resolve_provider_art_urls(
    server_item: ServerItem, *, app_config: Settings
) -> ResolvedArtUrls:
    """Resolve one provider item's artwork URLs to their public form.

    A resolution can be a name lookup, so it happens before the item's
    transaction opens rather than inside it.
    """
    return {
        url: public
        for url in set(_art_urls(server_item))
        if (public := await public_art_url(url, app_config=app_config))
    }


def _art_urls(server_item: ServerItem) -> Iterable[str]:
    """Yield every artwork URL one provider item carries."""
    for url in (
        server_item.poster_url,
        server_item.background_url,
        *(season.poster_url for season in server_item.seasons),
    ):
        if url:
            yield url


def apply_provider_art_urls(
    item: MediaItem,
    server_item: ServerItem,
    resolved: ResolvedArtUrls,
    *,
    only_missing: bool,
) -> bool:
    """Copy safe provider art URLs into the selected item asset slots."""
    # Both slots are applied before the result is combined: `or` between the
    # calls would skip the background as soon as the poster had changed.
    poster = apply_provider_art_url(
        item,
        ArtType.POSTER,
        server_item.poster_url,
        resolved,
        only_missing=only_missing,
    )
    background = apply_provider_art_url(
        item,
        ArtType.BACKGROUND,
        server_item.background_url,
        resolved,
        only_missing=only_missing,
    )
    return poster or background


def apply_provider_art_url(
    owner: MediaItem | Season,
    art_type: ArtType,
    url_val: str | None,
    resolved: ResolvedArtUrls,
    *,
    only_missing: bool,
) -> bool:
    """Persist a safe provider artwork URL while preserving local state."""
    saved_url = read_art_slot(owner, art_type).url

    if only_missing and saved_url:
        return False
    clean_url = resolved.get(url_val) if url_val else None
    if not clean_url or clean_url == saved_url:
        return False

    select_art(owner, art_type, clean_url)
    return True
