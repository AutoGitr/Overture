"""Jellyfin API client and shared MediaBrowser operations."""

lazy import operator
lazy from collections import Counter
lazy from collections.abc import AsyncIterator
lazy from itertools import batched
lazy from typing import ClassVar, override
lazy from urllib.parse import urlencode

lazy import httpx2
lazy from pydantic import TypeAdapter

lazy from ...db.models.media_item import MediaItem
lazy from ...domain import ArtType, MediaType
lazy from ...schemas.art import ArtCandidate
lazy from ...services.public_dataset.schema.contract import canonical_art_url
lazy from ...utils.art_urls import art_preview_url, art_source_label
lazy from ..adapters import ServerTheme
lazy from ..errors import MediaServerError
lazy from ..http_client import MediaServerHttpClient
lazy from ..wire import (
    MEDIA_BROWSER_SECTION_LIST,
    MediaBrowserItem,
    MediaBrowserSection,
    media_browser_items,
    media_browser_page,
    media_browser_server_id,
    parse_wire,
    remote_images_page,
)

#: The MediaBrowser image type that holds each art type.
IMAGE_TYPES = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ArtType.POSTER: "Primary",
        ArtType.SEASON_POSTER: "Primary",
        ArtType.BACKGROUND: "Backdrop",
    }
)
#: The library collection type that holds each media type.
COLLECTION_TYPES = frozendict({MediaType.MOVIE: "movies", MediaType.SHOW: "tvshows"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
#: The item type a library of each media type lists.
ITEM_TYPES = frozendict({MediaType.MOVIE: "Movie", MediaType.SHOW: "Series"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
_ITEM = TypeAdapter(MediaBrowserItem)


def _provider_ids(item: MediaBrowserItem) -> dict[str, str]:
    """Return an item's external IDs, keyed by lowercase provider name."""
    return {
        key.lower(): str(value)
        for key, value in (item.get("ProviderIds") or {}).items()
    }


class JellyfinClient(MediaServerHttpClient):
    """Interface to the Jellyfin Media Server API."""

    _PAGE_PARAMETERS: ClassVar[tuple[str, str]] = ("startIndex", "limit")
    # Each page re-runs the whole query: 16,571 episodes took 14 s in pages of
    # 100 and 0.6 s unpaged, while parsing costs about 4 KB per row. 5000 rows
    # stay near unpaged speed with a bounded page.
    _PAGE_SIZE: ClassVar[int] = 5000
    # Ids per People lookup; the batch size did not change the time measured.
    _PEOPLE_BATCH: ClassVar[int] = 100
    #: Item fields a library listing asks for. People is resolved per credit on
    #: the server, so listings carry only the movie Etag (its DateLastSaved) and
    #: get_people fetches on change.
    _ITEM_FIELDS: ClassVar[str] = (
        "ProviderIds,Path,Studios,DateCreated,DateLastMediaAdded"
    )

    @property
    def web_base_url(self) -> str:
        return self._app_config.MEDIA_SERVER_URL.rstrip("/")

    @property
    def api_base_url(self) -> str:
        return self.web_base_url

    @property
    @override
    def auth_headers(self) -> dict[str, str]:
        token = self._app_config.MEDIA_SERVER_API_KEY.get_secret_value()
        return {"Authorization": f'MediaBrowser Token="{token}"'}

    def query_params(self, **params: str) -> dict[str, str]:
        """Spell query parameters the way this server expects them."""
        return params

    def api_url(self, path: str, **params: str) -> str:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        return f"{url}?{urlencode(self.query_params(**params))}" if params else url

    @override
    async def _create_client(self) -> httpx2.AsyncClient:
        return self._client_factory(
            base_url=self.api_base_url,
            verify=self._app_config.media_server_verify_tls(),
            headers={**self.auth_headers, "Accept": "application/json"},
        )

    async def get_sections(self) -> list[MediaBrowserSection]:
        sections = parse_wire(
            MEDIA_BROWSER_SECTION_LIST, await self._get("/Library/VirtualFolders")
        )
        if len({section["ItemId"] for section in sections}) != len(sections):
            raise MediaServerError("Media server returned duplicate library IDs")
        return sections

    def _section_item_params(self, section_id: str, item_type: str) -> dict[str, str]:
        return self.query_params(
            parentId=section_id,
            fields=f"{self._ITEM_FIELDS},Etag"
            if item_type == "Movie"
            else self._ITEM_FIELDS,
            includeItemTypes=item_type,
            recursive="true",
            enableImages="true",
            enableImageTypes="Primary,Backdrop",
            imageTypeLimit="1",
            enableUserData="false",
        )

    def _season_params(self, parent_id: str) -> dict[str, str]:
        # ChildCount and RecursiveItemCount need a user, so episodes are counted.
        return self.query_params(
            parentId=parent_id,
            includeItemTypes="Season",
            recursive="true",
            enableImages="true",
            enableImageTypes="Primary",
            imageTypeLimit="1",
            enableUserData="false",
        )

    def _episode_params(self, parent_id: str) -> dict[str, str]:
        return self.query_params(
            parentId=parent_id,
            includeItemTypes="Episode",
            recursive="true",
            enableImages="false",
            enableUserData="false",
        )

    async def _items(self, path: str, params: dict[str, str]) -> list[MediaBrowserItem]:
        return await self._pages(
            path,
            params=params,
            parse=media_browser_page,
            identity=operator.itemgetter("Id"),
        )

    def _item_pages(
        self, params: dict[str, str]
    ) -> AsyncIterator[list[MediaBrowserItem]]:
        """Yield validated pages of one large ``/Items`` listing."""
        return self._page_batches(
            "/Items",
            params=params,
            parse=media_browser_page,
            identity=operator.itemgetter("Id"),
            track_all_ids=False,
            require_total=True,
        )

    def iter_section_items(
        self, section_id: str, item_type: str
    ) -> AsyncIterator[list[MediaBrowserItem]]:
        """Yield validated media pages without retaining the whole section."""
        return self._item_pages(self._section_item_params(section_id, item_type))

    def iter_seasons(self, parent_id: str) -> AsyncIterator[list[MediaBrowserItem]]:
        """Yield the season rows under a library or show, in one listing."""
        return self._item_pages(self._season_params(parent_id))

    async def count_episodes_by_season(self, parent_id: str) -> Counter[str]:
        """Count the episodes under a library or show by their season ID."""
        counts: Counter[str] = Counter()
        async for page in self._item_pages(self._episode_params(parent_id)):
            counts.update(
                season_id for episode in page if (season_id := episode.get("SeasonId"))
            )
        return counts

    async def get_people(self, item_ids: list[str]) -> list[MediaBrowserItem]:
        """Return the given items with only their credited people."""
        items: list[MediaBrowserItem] = []
        for batch in batched(item_ids, self._PEOPLE_BATCH, strict=False):
            items += await self._items(
                "/Items",
                self.query_params(
                    ids=",".join(batch),
                    fields="People",
                    enableImages="false",
                    enableUserData="false",
                ),
            )
        return items

    @override
    async def find_item_id(self, item: MediaItem) -> str | None:
        """Find an item by its external IDs, memoized per item identity."""
        wanted = {
            key: str(value)
            for key, value in (
                ("tmdb", item.tmdb_id),
                ("tvdb", item.tvdb_id),
                ("imdb", item.imdb_id),
            )
            if value is not None
        }
        if not wanted:
            return None
        return await self._cache.get_or_compute(
            ("find_item", item.media_type, *sorted(wanted.items())),
            self._find_item_id,
            MediaType(item.media_type),
            item.title,
            wanted,
        )

    async def _find_item_id(
        self, media_type: MediaType, title: str, wanted: dict[str, str]
    ) -> str | None:
        """Search the item's title and match the results by external ID."""
        for metadata in await self._items(
            "/Items",
            self.query_params(
                searchTerm=title,
                includeItemTypes=ITEM_TYPES[media_type],
                recursive="true",
                fields="ProviderIds",
                enableImages="false",
                enableUserData="false",
            ),
        ):
            ids = _provider_ids(metadata)
            if any(ids.get(key) == value for key, value in wanted.items()):
                return metadata["Id"]
        return None

    @override
    async def find_season_id(self, show_id: str, season_num: int) -> str | None:
        for season in media_browser_items(await self._get(f"/Shows/{show_id}/Seasons")):
            if season.get("IndexNumber") == season_num:
                return season["Id"]
        return None

    async def get_active_image_url(self, item_id: str, art_type: ArtType) -> str | None:
        path = f"/Items/{item_id}/Images/{IMAGE_TYPES[art_type]}"
        response = await self._request("HEAD", path, allow_not_found=True)
        return None if response.status_code == 404 else self.api_url(path)

    @override
    async def get_art_candidates(
        self, item_id: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        return await self._cache.get_or_compute(
            ("art", item_id, art_type),
            self._get_art_candidates,
            item_id,
            art_type,
        )

    async def _get_art_candidates(
        self, item_id: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        images = await self._pages(
            f"/Items/{item_id}/RemoteImages",
            params=self.query_params(
                type=IMAGE_TYPES[art_type], includeAllLanguages="true"
            ),
            parse=remote_images_page,
            identity=None,
        )
        results: list[ArtCandidate] = []
        seen: set[str] = set()
        for image in images:
            try:
                url = canonical_art_url(image["Url"])
            except ValueError:
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append(
                ArtCandidate(
                    url=url,
                    preview_url=art_preview_url(url, art_type)
                    or image.get("ThumbnailUrl")
                    or url,
                    width=image.get("Width") or 0,
                    height=image.get("Height") or 0,
                    source=art_source_label(url),
                )
            )
        return results

    async def refresh_item(self, item_id: str) -> None:
        await self._request(
            "POST",
            f"/Items/{item_id}/Refresh",
            params=self.query_params(
                metadataRefreshMode="FullRefresh", imageRefreshMode="FullRefresh"
            ),
        )

    async def get_item(self, item_id: str) -> MediaBrowserItem:
        return parse_wire(_ITEM, await self._get(f"/Items/{item_id}"))

    async def _theme_items(self, item_id: str) -> list[MediaBrowserItem]:
        return media_browser_items(
            await self._get(
                f"/Items/{item_id}/ThemeSongs",
                params=self.query_params(inheritFromParent="false"),
            )
        )

    @override
    async def get_theme_songs(self, item_id: str) -> list[ServerTheme]:
        """Return the item's theme songs with the file each one plays."""
        results: list[ServerTheme] = []
        for theme in await self._theme_items(item_id):
            ticks = theme.get("RunTimeTicks")
            if ticks is None:
                ticks = (await self.get_item(theme["Id"])).get("RunTimeTicks")
            results.append(
                ServerTheme(
                    id=theme["Id"],
                    title=theme.get("Name") or "theme",
                    path=theme.get("Path"),
                    duration=ticks / 10_000_000 if ticks is not None else None,
                )
            )
        return results

    async def delete_item(self, item_id: str) -> None:
        await self._request("DELETE", f"/Items/{item_id}")

    @override
    async def test_connection(self) -> bool:
        try:
            return bool(media_browser_server_id(await self._get("/System/Info")))
        except MediaServerError:
            return False
