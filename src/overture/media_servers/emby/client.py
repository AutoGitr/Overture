"""Emby API client built on the shared MediaBrowser protocol."""

lazy import operator
lazy from typing import ClassVar, override

lazy from ...domain import MediaType
lazy from ..errors import MediaServerError
lazy from ..jellyfin.client import ITEM_TYPES, JellyfinClient
lazy from ..wire import (
    MediaBrowserItem,
    MediaBrowserSection,
    media_browser_sections_page,
    media_browser_server_id,
)


class EmbyClient(JellyfinClient):
    """Interface to the Emby Server API.

    Emby speaks the MediaBrowser API Jellyfin forked from, with capitalized
    query parameters and a few differently named fields.
    """

    _PAGE_PARAMETERS: ClassVar[tuple[str, str]] = ("StartIndex", "Limit")
    _ITEM_FIELDS: ClassVar[str] = "ProviderIds,Path,Studios,DateCreated,ProductionYear"

    @property
    @override
    def web_base_url(self) -> str:
        """Return the Emby server root, accepting URLs ending in ``/emby``."""
        base = self._app_config.MEDIA_SERVER_URL.rstrip("/")
        return base[:-5] if base.lower().endswith("/emby") else base

    @property
    @override
    def api_base_url(self) -> str:
        """Return Emby's API base URL."""
        return f"{self.web_base_url}/emby"

    @property
    @override
    def auth_headers(self) -> dict[str, str]:
        """Authenticate using Emby's API-key header."""
        return {
            "X-Emby-Token": self._app_config.MEDIA_SERVER_API_KEY.get_secret_value()
        }

    @override
    def query_params(self, **params: str) -> dict[str, str]:
        return {key[0].upper() + key[1:]: value for key, value in params.items()}

    @override
    async def get_sections(self) -> list[MediaBrowserSection]:
        return await self._pages(
            "/Library/VirtualFolders/Query",
            params=None,
            parse=media_browser_sections_page,
            identity=operator.itemgetter("ItemId"),
        )

    @override
    async def _find_item_id(
        self, media_type: MediaType, title: str, wanted: dict[str, str]
    ) -> str | None:
        """Ask Emby for the item by its external IDs directly."""
        items = await self._items(
            "/Items",
            self.query_params(
                anyProviderIdEquals=",".join(
                    f"{key}.{value}" for key, value in wanted.items()
                ),
                includeItemTypes=ITEM_TYPES[media_type],
                recursive="true",
                enableImages="false",
                enableUserData="false",
            ),
        )
        return items[0]["Id"] if items else None

    @override
    async def get_item(self, item_id: str) -> MediaBrowserItem:
        items = await self._items("/Items", self.query_params(ids=item_id))
        if len(items) != 1 or items[0]["Id"] != item_id:
            raise MediaServerError("Media server did not return the requested item")
        return items[0]

    @override
    async def _theme_items(self, item_id: str) -> list[MediaBrowserItem]:
        return await self._items(
            f"/Items/{item_id}/ThemeSongs",
            self.query_params(inheritFromParent="false", fields="Path"),
        )

    async def get_server_id(self) -> str:
        """Return the stable Emby server ID used by web deep links."""

        async def fetch() -> str:
            return media_browser_server_id(await self._get("/System/Info"))

        return await self._cache.get_or_compute(("emby_server_id",), fetch)
