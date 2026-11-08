"""Emby adapter built on the shared MediaBrowser provider behavior."""

lazy from typing import ClassVar, override

lazy from ...config import Settings
lazy from ...domain import ServerType
lazy from ..adapters import NoCollectionThemes, ServerWebLinks
lazy from ..health import MediaServerHealthTracker
lazy from ..jellyfin.provider import MediaBrowserProvider
lazy from .client import EmbyClient


class EmbyProvider(MediaBrowserProvider[EmbyClient]):
    """Adapt Emby responses to the shared media-server contract."""

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

    @override
    async def web_links(self) -> ServerWebLinks:
        """Return Emby web links, which name the server as well as the item."""
        link = (
            f"{self.client.web_base_url}/web/index.html#!/item?id={{id}}"
            f"&serverId={await self.client.get_server_id()}"
        )
        return ServerWebLinks(item=link, collection=link)
