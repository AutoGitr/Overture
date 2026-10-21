"""Runtime-owned HTTP clients for remote image and media payloads."""

lazy import httpx2

lazy from ..config import Settings
lazy from .http import LazyClient, create_client


class ProxyClientManager:
    """Lazily create bounded clients shared by outbound media workflows.

    One client verifies TLS and one does not, for a media server the user
    configured with ``MEDIA_SERVER_VERIFY_TLS=false``; each URL gets the one
    its origin's TLS policy calls for.
    """

    def __init__(self, *, app_config: Settings) -> None:
        self._app_config = app_config
        limits = httpx2.Limits(max_connections=100, max_keepalive_connections=50)

        def lazy(verify: bool) -> LazyClient:
            async def build() -> httpx2.AsyncClient:
                return create_client(
                    verify=verify, follow_redirects=False, limits=limits
                )

            return LazyClient(build, name="Proxy")

        self._clients = {verify: lazy(verify) for verify in (True, False)}

    async def get_client(self, url: str | None = None) -> httpx2.AsyncClient:
        """Return the client whose TLS policy fits *url*."""
        return await self._clients[self._app_config.media_server_verify_tls(url)].get()

    async def close(self) -> None:
        """Close both clients."""
        for client in self._clients.values():
            await client.close()
