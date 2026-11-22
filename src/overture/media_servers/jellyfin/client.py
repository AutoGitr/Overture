"""Jellyfin API client and shared MediaBrowser operations."""

lazy import base64
lazy import operator
lazy from collections import Counter
lazy from collections.abc import AsyncIterator
lazy from itertools import batched
lazy from pathlib import PurePath, PurePosixPath, PureWindowsPath
lazy from typing import Any, ClassVar, override
lazy from urllib.parse import urlencode

lazy import httpx2
lazy from pydantic import TypeAdapter

lazy from ...catalog_contract.contract import canonical_art_url
lazy from ...domain import ArtType, CollectionOrder, MediaType
lazy from ...schemas.art import ArtCandidate
lazy from ...utils.art_urls import art_preview_url, art_source_label
lazy from ..adapters import CollectionDetails, ItemIdentity, MemberWrite, ServerTheme
lazy from ..errors import MediaServerError
lazy from ..http_client import MediaServerHttpClient
lazy from ..wire import (
    MEDIA_BROWSER_SECTION_LIST,
    MediaBrowserImage,
    MediaBrowserItem,
    MediaBrowserSection,
    media_browser_items,
    media_browser_page,
    media_browser_server_id,
    media_browser_users,
    parse_wire,
    remote_images_page,
    wire_object,
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
_IMAGES = TypeAdapter(list[MediaBrowserImage])


def _server_path(path: str) -> PurePath:
    """Return a path as the server spells it, which may be a Windows one."""
    return PureWindowsPath(path) if "\\" in path else PurePosixPath(path)


def provider_ids(item: MediaBrowserItem) -> dict[str, str]:
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
    # Ids per collection membership write, which carries them in the query
    # string. A 32-character ID spells 35 with its encoded comma, so 200 fit
    # the 8 KiB request line Kestrel accepts by default; more fail with 414.
    _MEMBER_BATCH: ClassVar[int] = 200
    #: Item fields a library listing asks for. People is resolved per credit on
    #: the server, so listings carry only the movie Etag (its DateLastSaved) and
    #: get_people fetches on change.
    _ITEM_FIELDS: ClassVar[str] = (
        "Genres,ProviderIds,Path,Studios,DateCreated,DateLastMediaAdded,"
        "Tags,ProductionLocations,Width,SortName"
    )
    #: Lists a library's titles each on its own. With grouping into
    #: collections on, Jellyfin lists a collection in place of its titles,
    #: as if it were one of them.
    _UNGROUPED: ClassVar[dict[str, str]] = {"collapseBoxSetItems": "false"}
    #: Item fields an update sends back beside a listing's, so it keeps them.
    _DETAIL_FIELDS: ClassVar[str] = "Overview,Taglines"

    @property
    def web_base_url(self) -> str:
        return self.server.url.rstrip("/")

    @property
    def api_base_url(self) -> str:
        return self.web_base_url

    @property
    @override
    def auth_headers(self) -> dict[str, str]:
        token = self.server.api_key.get_secret_value()
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
            verify=self.server.verify_tls_for(),
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
            **self._UNGROUPED,
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

    async def get_boxsets(self) -> list[MediaBrowserItem]:
        """Return every collection (BoxSet) with its folder and provider IDs."""
        return await self._items(
            "/Items",
            self.query_params(
                includeItemTypes="BoxSet",
                recursive="true",
                fields="Genres,ProviderIds,Path,DateCreated,Overview",
                enableImages="true",
                enableImageTypes="Primary,Backdrop",
                imageTypeLimit="1",
                enableUserData="false",
            ),
        )

    async def get_boxset_member_ids(self, boxset_id: str) -> list[str]:
        """Return the IDs of the items a BoxSet holds."""
        children = await self._items(
            "/Items",
            self.query_params(
                parentId=boxset_id,
                **await self._member_reader(),
                enableImages="false",
                enableUserData="false",
            ),
        )
        return [child["Id"] for child in children]

    async def _member_reader(self) -> dict[str, str]:
        """Who a BoxSet's items are listed to.

        Jellyfin 12 lists them only to a user, and an API key has none, so they
        are asked for as an administrator, who sees every library.
        """
        return {"userId": await self._administrator()}

    async def _administrator(self) -> str:
        """The ID of a user who sees every library, fetched once."""

        async def fetch() -> str:
            admin = next(
                (
                    user
                    for user in media_browser_users(await self._get("/Users"))
                    if (user.get("Policy") or {}).get("IsAdministrator")
                ),
                None,
            )
            if admin is None:
                raise MediaServerError(
                    f"{self.server.title} has no administrator to list "
                    "collection members as"
                )
            return str(admin["Id"])

        return await self._cache.get_or_compute(("administrator",), fetch)

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
    async def find_item_id(self, item: ItemIdentity) -> str | None:
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
                **self._UNGROUPED,
            ),
        ):
            ids = provider_ids(metadata)
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
            idempotent=True,
        )

    async def has_item(self, item_id: str) -> bool:
        """Whether the server still holds the item."""
        found = media_browser_items(
            await self._get(
                "/Items",
                params=self.query_params(
                    ids=item_id, enableImages="false", enableUserData="false"
                ),
            )
        )
        return any(row["Id"] == item_id for row in found)

    async def get_item(self, item_id: str) -> MediaBrowserItem:
        return parse_wire(_ITEM, await self._item_details(item_id))

    async def _item_details(self, item_id: str) -> dict[str, Any]:
        """One item with every field a metadata update sends back.

        Asked as a query by ID: Jellyfin 12 refuses ``/Items/{id}`` without a
        user, which an API key has none of.
        """
        data = wire_object(
            await self._get(
                "/Items",
                params=self.query_params(
                    ids=item_id, fields=f"{self._ITEM_FIELDS},{self._DETAIL_FIELDS}"
                ),
            )
        )
        rows: list[dict[str, Any]] = data.get("Items") or []
        if len(rows) != 1 or rows[0].get("Id") != item_id:
            raise MediaServerError(f"{self.server.title} did not return item {item_id}")
        return rows[0]

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

    async def drop_downloaded_backdrops(self, item_id: str) -> None:
        """Delete the backdrops the server keeps outside the item's folder.

        A refresh adds the backdrops beside the media after the ones the item
        already has, so the one it shows stays the first the server
        downloaded. Those live in the server's metadata folder and can be
        downloaded again; files beside the media are left alone.
        """
        item = await self.get_item(item_id)
        if not (path := item.get("Path")):
            return
        media = _server_path(path)
        folder = media if item.get("IsFolder") else media.parent
        images = parse_wire(_IMAGES, await self._get(f"/Items/{item_id}/Images"))
        downloaded = sorted(
            (
                image.get("ImageIndex") or 0
                for image in images
                if image["ImageType"] == "Backdrop"
                and (kept := image.get("Path"))
                and not _server_path(kept).is_relative_to(folder)
            ),
            reverse=True,
        )
        # Deleting one moves those after it up, so the last goes first.
        for index in downloaded:
            await self._request(
                "DELETE",
                f"/Items/{item_id}/Images/Backdrop/{index}",
                allow_not_found=True,
            )

    async def delete_image(self, item_id: str, art_type: ArtType) -> None:
        """Delete an item's first image of the art type; a saved file goes with it."""
        await self._request(
            "DELETE",
            f"/Items/{item_id}/Images/{IMAGE_TYPES[art_type]}",
            allow_not_found=True,
        )

    @override
    async def test_connection(self) -> bool:
        try:
            return bool(media_browser_server_id(await self._get("/System/Info")))
        except MediaServerError:
            return False

    async def create_collection(self, title: str, member_ids: list[str]) -> str:
        """Create a BoxSet holding ``member_ids``."""
        response = await self._request(
            "POST", "/Collections", params=self.query_params(name=title)
        )
        value = wire_object(self._json(response))
        if not isinstance(value.get("Id"), str) or not value["Id"]:
            raise MediaServerError("Media server did not return the new collection ID")
        collection_id = str(value["Id"])
        await self._change_members("POST", collection_id, member_ids)
        return collection_id

    async def set_collection_members(
        self, collection_id: str, member_ids: list[str], *, append: bool = False
    ) -> MemberWrite:
        """Apply only additions and removals to a BoxSet."""
        current_ids = await self.get_boxset_member_ids(collection_id)
        current = set(current_ids)
        if append:
            requested = set(member_ids)
            member_ids = [
                *member_ids,
                *(identity for identity in current_ids if identity not in requested),
            ]
        wanted = set(member_ids)
        additions, removals = sorted(wanted - current), sorted(current - wanted)
        await self._change_members("POST", collection_id, additions)
        await self._change_members("DELETE", collection_id, removals)
        return MemberWrite(member_ids, len(additions), len(removals))

    async def _change_members(
        self, method: str, collection_id: str, member_ids: list[str]
    ) -> None:
        """Add (``POST``) or remove (``DELETE``) BoxSet members in batches."""
        for batch in batched(member_ids, self._MEMBER_BATCH, strict=False):
            await self._request(
                method,
                f"/Collections/{collection_id}/Items",
                params=self.query_params(ids=",".join(batch)),
            )

    async def update_collection_details(
        self, collection_id: str, details: CollectionDetails
    ) -> None:
        """Send the details a BoxSet keeps, in the complete DTO the server requires.

        A BoxSet keeps no mode, visibility or filtering.
        """
        item = await self.collection_metadata(collection_id)
        item.update(
            Name=details.title,
            DisplayOrder="PremiereDate"
            if details.order is CollectionOrder.RELEASE_ASC
            else "SortName",
        )
        if details.summary is not None:
            item["Overview"] = details.summary
        if details.sort_title is not None:
            self._set_sort_title(item, details.sort_title)
        await self._request("POST", f"/Items/{collection_id}", json=item)

    @staticmethod
    def _set_sort_title(details: dict[str, Any], sort_title: str) -> None:
        """Set or, when empty, release the sort title in an item update.

        Jellyfin keeps a forced sort name through refreshes and refuses
        ``SortName`` as a locked field.
        """
        details["ForcedSortName"] = sort_title or None

    async def upload_collection_art(
        self, collection_id: str, art_type: ArtType, image_bytes: bytes, mime_type: str
    ) -> None:
        """MediaBrowser accepts base64 image data with the original image type."""
        await self._request(
            "POST",
            f"/Items/{collection_id}/Images/{IMAGE_TYPES[art_type]}",
            content=base64.b64encode(image_bytes),
            headers={"Content-Type": mime_type},
        )

    async def collection_metadata(self, collection_id: str) -> dict[str, Any]:
        """Read the complete DTO so metadata edits preserve unrelated fields."""
        return await self._item_details(collection_id)
