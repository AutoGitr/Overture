"""Artwork URL policy.

Which link forms each art source serves, and the one canonical full-size link
they all become, is the OvertureDB contract's to say: ``canonical_art_url``
there is the only place that knows it. This module adds what Overture itself
needs on top: whether a link may be stored as public artwork, the smaller
rendition shown while browsing, and a short name for where artwork comes from.
"""

lazy import asyncio
lazy from urllib.parse import urlsplit

lazy from ..config import Settings, in_plex_direct_domain
lazy from ..domain import ArtSource, ArtType
lazy from ..services.public_dataset.schema.contract import (
    art_source,
    canonical_art_url,
    preview_art_url,
)
lazy from .security import remove_sensitive_url_params
lazy from .ssrf import is_private_url

#: Preview widths of TMDB's own size ladder, by the shape of the slot.
_TMDB_PREVIEW_SIZES = frozendict(
    {ArtType.POSTER: "w342", ArtType.SEASON_POSTER: "w342"}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
_TMDB_DEFAULT_PREVIEW_SIZE = "w780"


async def public_art_url(
    value: str | None,
    *,
    dns_cache: dict[str, asyncio.Task[bool]] | None = None,
    fetched_publicly: bool = False,
    app_config: Settings,
) -> str | None:
    """Return the canonical form of *value* when it is safe to store publicly.

    *fetched_publicly* says the caller has just fetched the URL through the
    private-address guard, so resolving its host again would only let a
    transient DNS failure discard a selection that was already proven public.
    """
    if not value:
        return None
    try:
        clean = canonical_art_url(remove_sensitive_url_params(value))
    except ValueError:
        return None
    hostname = urlsplit(clean).hostname or ""
    if in_plex_direct_domain(hostname) or app_config.is_trusted_media_server_url(clean):
        return None
    if not fetched_publicly and await is_private_url(clean, dns_cache=dns_cache):
        return None
    return clean


def art_preview_url(url: str, art_type: ArtType) -> str | None:
    """Return a smaller rendition of canonical artwork, when its source has one."""
    return preview_art_url(
        url, size=_TMDB_PREVIEW_SIZES.get(art_type, _TMDB_DEFAULT_PREVIEW_SIZE)
    )


def selected_art_source(
    url: str | None, overturedb_url: str | None
) -> ArtSource | None:
    """Return where a slot's selected artwork comes from.

    Artwork the OvertureDB catalog holds for the slot counts as OvertureDB's,
    whichever host serves it; links to hosts the catalog does not use have no
    source.
    """
    if not url:
        return None
    if url == overturedb_url:
        return ArtSource.OVERTUREDB
    source = art_source(url)
    return ArtSource(source) if source in ArtSource else None


def art_source_label(url: str) -> str:
    """Return where artwork comes from: its art source, else its site's name."""
    if source := art_source(url):
        return source
    try:
        hostname = urlsplit(url).hostname or ""
    except ValueError:
        hostname = ""
    labels = hostname.rstrip(".").split(".")
    return labels[-2] if len(labels) >= 2 else hostname or "external"
