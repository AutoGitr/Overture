"""Fetching remote artwork for comparison, and a bounded cache of its pHashes.

Matching fetches the same candidate images again and again, so each URL's
pHash is cached with per-URL stampede protection: concurrent match jobs do not
re-fetch and re-hash the same image.
"""

lazy import logging

lazy import httpx2

lazy from ...config import Settings
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...utils.cache import AsyncMemoizer
lazy from ...utils.image import FetchedImage, fetch_image
lazy from .phash import PhashService

logger = logging.getLogger(__name__)


async def fetch_art(
    url: str,
    *,
    provider_registry: ProviderRegistry,
    image_clients: ProxyClientManager,
    app_config: Settings,
) -> FetchedImage:
    """Fetch an artwork image for comparison.

    Only the configured media server's own URLs may resolve to a private
    address, and only they carry its credentials.
    """
    return await fetch_image(
        url,
        await image_clients.get_client(url),
        allow_private=app_config.is_trusted_media_server_url(url),
        headers=provider_registry.provider.get_download_headers(url),
    )


class ArtMatcherCache:
    """Bounded URL pHash cache with per-URL stampede protection."""

    def __init__(
        self,
        *,
        phash: PhashService,
        provider_registry: ProviderRegistry,
        image_clients: ProxyClientManager,
        maxsize: int = 4096,
        app_config: Settings,
    ) -> None:
        self._app_config = app_config
        self._phash = phash
        self._provider_registry = provider_registry
        self._image_clients = image_clients
        self._hashes: AsyncMemoizer[str] = AsyncMemoizer(maxsize=maxsize)

    async def close(self) -> None:
        """Release shared image hash computations."""
        await self._hashes.close()

    async def fetch(self, url: str) -> FetchedImage:
        """Fetch an artwork image for comparison; see :func:`fetch_art`."""
        return await fetch_art(
            url,
            provider_registry=self._provider_registry,
            image_clients=self._image_clients,
            app_config=self._app_config,
        )

    async def cached_url_phash(self, url: str, *, fresh: bool = False) -> str | None:
        """Return the pHash for *url*, computing and caching when needed."""

        async def compute() -> str:
            return await self._phash.compute_from_bytes((await self.fetch(url)).data)

        try:
            return (
                await compute()
                if fresh
                else await self._hashes.get_or_compute(url, compute)
            )
        except (httpx2.HTTPError, OSError, ValueError) as exc:
            logger.debug("Could not fingerprint a remote image: %s", exc)
            return None
