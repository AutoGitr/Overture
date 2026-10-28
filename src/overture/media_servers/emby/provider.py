"""Emby adapter built on the shared MediaBrowser provider behavior."""

lazy from collections.abc import AsyncIterator
lazy from datetime import datetime
lazy from typing import ClassVar, override

lazy from ...config import Settings
lazy from ...domain import ServerType
lazy from ..adapters import NoCollectionThemes, ServerItem
lazy from ..health import MediaServerHealthTracker
lazy from ..jellyfin.provider import MediaBrowserProvider
lazy from .client import EmbyClient


class EmbyProvider(MediaBrowserProvider[EmbyClient]):
    """Adapt Emby responses to the shared media-server contract.

    Emby web links name the server, so its ID is read before links are built.
    """

    server_type: ClassVar[ServerType] = ServerType.EMBY
    collections = NoCollectionThemes()

    def __init__(
        self,
        *,
        client: EmbyClient | None = None,
        app_config: Settings,
        health: MediaServerHealthTracker | None = None,
    ) -> None:
        super().__init__(
            client=client or EmbyClient(app_config=app_config, health=health),
            app_config=app_config,
        )
        self._server_id = ""

    @override
    async def _iter_items(
        self, library_ids: list[str] | None, since: datetime | None
    ) -> AsyncIterator[list[ServerItem]]:
        self._server_id = await self.client.get_server_id()
        async for page in super()._iter_items(library_ids, since):
            yield page

    @override
    async def build_item_link(self, server_item_id: str) -> str:
        """Return an Emby web link, resolving the server identity if needed."""
        self._server_id = await self.client.get_server_id()
        return self.server_link(server_item_id)

    @override
    def server_link(self, server_item_id: str) -> str:
        """Return an Emby web link for an item."""
        return (
            f"{self.client.web_base_url}/web/index.html#!/item?id={server_item_id}"
            f"&serverId={self._server_id}"
        )
