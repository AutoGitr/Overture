"""Plex media-server adapter."""

lazy from collections.abc import AsyncIterator, Collection
lazy from datetime import datetime
lazy from typing import ClassVar, Literal, override

lazy from ...config import Settings
lazy from ...domain import (
    ArtType,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    ImageSize,
    MediaType,
    ServerAsset,
    ServerType,
)
lazy from ...utils.security import remove_sensitive_url_params
lazy from ...utils.time import parse_utc_datetime
lazy from ..adapters import (
    MAX_SEASONS_PER_SHOW,
    ProviderImageRequest,
    ServerCollection,
    ServerItem,
    ServerSeason,
    ServerSection,
    UploadThemes,
    server_path,
)
lazy from ..base import BaseMediaServerProvider
lazy from ..errors import MediaServerError
lazy from ..wire import PlexMetadata
lazy from .client import (
    PLEX_COLLECTION_FILTERING,
    PLEX_COLLECTION_MODES,
    PLEX_COLLECTION_SORTS,
    PLEX_CUSTOM_SORT,
    PlexClient,
    plex_web_link,
)

#: The Plex field that holds each asset, as named by its ``<field>.locked`` flag.
_PLEX_ASSET_FIELD: frozendict[ServerAsset, Literal["thumb", "art", "theme"]] = (
    frozendict(
        {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
            ServerAsset.POSTER: "thumb",
            ServerAsset.SEASON_POSTER: "thumb",
            ServerAsset.BACKGROUND: "art",
            ServerAsset.THEME: "theme",
        }
    )
)
#: Plex names its library types as Overture names media types.
_PLEX_MEDIA_TYPES = frozendict(
    {media_type.value: media_type for media_type in MediaType}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


#: Plex lists a collection's preferences as the numbers it stores.
_PLEX_COLLECTION_MODES = frozendict(
    {str(n): mode for mode, n in PLEX_COLLECTION_MODES.items()}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
_PLEX_COLLECTION_ORDERS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        **{str(n): order for order, n in PLEX_COLLECTION_SORTS.items()},
        str(PLEX_CUSTOM_SORT): CollectionOrder.CUSTOM,
    }
)
_PLEX_COLLECTION_FILTERING = frozendict(
    {str(n): mode for mode, n in PLEX_COLLECTION_FILTERING.items()}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


def _art_field(art_type: ArtType) -> Literal["thumb", "art"]:
    """Return the Plex field that holds *art_type*."""
    return "art" if art_type is ArtType.BACKGROUND else "thumb"


def _rating(value: float | None) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _first_mapping[T](value: list[T] | None) -> T | None:
    return value[0] if value else None


def _plex_location_path(metadata: PlexMetadata) -> str | None:
    """Return the first Plex library location path from item metadata."""
    location = _first_mapping(metadata.get("Location"))
    path = location.get("path") if location else None
    return str(path) if path else None


def _plex_movie_file_parent(metadata: PlexMetadata) -> str | None:
    """Return the parent folder for the first Plex movie part file."""
    media = _first_mapping(metadata.get("Media"))
    part = _first_mapping(media.get("Part")) if media else None
    file_path = part.get("file") if part else None
    return str(server_path(str(file_path)).parent) if file_path else None


def _plex_absolute_url(path: str | None, plex_base: str) -> str | None:
    """Return an absolute, credential-free Plex URL for an image path."""
    if not path:
        return None
    if path.startswith("http"):
        return remove_sensitive_url_params(path)
    if path.startswith("/"):
        return remove_sensitive_url_params(f"{plex_base}{path}")
    return None


def _plex_guids(metadata: PlexMetadata) -> dict[str, str]:
    """Return the external ids Plex reports, keyed by agent."""
    guids: dict[str, str] = {}
    for entry in metadata.get("Guid") or []:
        gid = entry.get("id", "")
        if "://" in gid:
            agent, external_id = gid.split("://", 1)
            guids[agent] = external_id
    return guids


def _plex_season(season: PlexMetadata, plex_base: str) -> ServerSeason:
    """Normalize one season row; ``leafCount`` is its episode count."""
    season_num = season.get("index", 0)
    file_count = season.get("leafCount")
    if file_count is None:
        raise MediaServerError("Plex returned a season without its episode count")
    return ServerSeason(
        num=season_num,
        title=season.get(
            "title", f"Season {season_num}" if season_num > 0 else "Specials"
        ),
        file_count=file_count,
        server_item_id=str(season["ratingKey"]),
        poster_url=_plex_absolute_url(season.get("thumb"), plex_base),
    )


class PlexProvider(BaseMediaServerProvider[PlexClient]):
    """Adapt Plex responses to the shared media-server contract."""

    server_type: ClassVar[ServerType] = ServerType.PLEX
    collections = UploadThemes()

    def __init__(
        self, *, client: PlexClient | None = None, app_config: Settings
    ) -> None:
        super().__init__(
            client=client or PlexClient(app_config=app_config), app_config=app_config
        )

    def _item_link(self, rating_key: str, machine_id: str | None) -> str:
        return plex_web_link(
            "metadata", rating_key, machine_id, app_config=self._app_config
        )

    @override
    async def _list_sections(self) -> list[ServerSection]:
        """Return Plex's movie and show sections."""
        return [
            ServerSection(
                key=str(section["key"]),
                title=section.get("title") or str(section["key"]),
                media_type=media_type,
            )
            for section in await self.client.get_sections()
            if (media_type := _PLEX_MEDIA_TYPES.get(section["type"]))
        ]

    async def _fill_show_details(self, shows: list[ServerItem], plex_base: str) -> None:
        """Fill the folders and seasons of a page of shows in one request.

        A show's season rows must number its ``childCount``, so a shortened
        list fails the sync instead of dropping seasons.
        """
        details = {
            str(row["ratingKey"]): row
            for row in await self.client.get_shows_with_seasons(
                [show.id for show in shows]
            )
        }
        for show in shows:
            row = details.get(show.id)
            if row is None:
                raise MediaServerError("Plex did not return a listed show")
            seasons = (row.get("Children") or {}).get("Metadata", [])
            if len(seasons) != (row.get("childCount") or 0):
                raise MediaServerError("Plex returned an incomplete season list")
            if len(seasons) > MAX_SEASONS_PER_SHOW:
                raise MediaServerError("Media server returned too many seasons")
            show.folder_path = _plex_location_path(row)
            show.seasons = [
                _plex_season(season, plex_base)
                for season in sorted(seasons, key=lambda season: season.get("index", 0))
            ]

    def _to_server_item(
        self,
        metadata: PlexMetadata,
        *,
        media_type: MediaType,
        section_key: str,
        plex_base: str,
        machine_id: str | None,
    ) -> ServerItem:
        """Normalize one Plex row, without a show's folder or seasons."""
        rating_key = str(metadata.get("ratingKey", ""))
        movie = media_type is MediaType.MOVIE
        directors = metadata.get("Director") or []
        media_list = metadata.get("Media") or []
        first_media = media_list[0] if media_list else None
        duration_ms = metadata.get("duration")
        # Plex leaves out zero counts and offsets.
        plays = metadata.get("viewCount") or 0
        leaves = metadata.get("leafCount") or 0
        return ServerItem(
            id=rating_key,
            title=metadata.get("title", ""),
            year=metadata.get("year"),
            media_type=media_type,
            guids=_plex_guids(metadata),
            poster_url=_plex_absolute_url(metadata.get("thumb"), plex_base),
            background_url=_plex_absolute_url(metadata.get("art"), plex_base),
            server_link=self._item_link(rating_key, machine_id),
            library_id=section_key,
            folder_path=(
                _plex_location_path(metadata) or _plex_movie_file_parent(metadata)
                if movie
                else None
            ),
            director=(directors[0].get("tag") if directors else None)
            if movie
            else None,
            studio=metadata.get("studio") or None,
            genres=tuple(
                tag for g in metadata.get("Genre") or [] if (tag := g.get("tag"))
            ),
            actors=tuple(
                tag for r in metadata.get("Role") or [] if (tag := r.get("tag"))
            ),
            writers=tuple(
                tag for w in metadata.get("Writer") or [] if (tag := w.get("tag"))
            ),
            producers=tuple(
                tag for p in metadata.get("Producer") or [] if (tag := p.get("tag"))
            ),
            countries=tuple(
                tag for c in metadata.get("Country") or [] if (tag := c.get("tag"))
            ),
            labels=tuple(
                tag for lbl in metadata.get("Label") or [] if (tag := lbl.get("tag"))
            ),
            content_rating=metadata.get("contentRating") or None,
            edition=(metadata.get("editionTitle") or None) if movie else None,
            resolution=(first_media.get("videoResolution") if first_media else None)
            or None,
            critic_rating=_rating(metadata.get("rating")),
            audience_rating=_rating(metadata.get("audienceRating")),
            user_rating=_rating(metadata.get("userRating")),
            duration_minutes=int(duration_ms // 60000)
            if isinstance(duration_ms, int) and duration_ms > 0
            else None,
            plays=plays,
            last_played_at=parse_utc_datetime(metadata.get("lastViewedAt")),
            # Plex's unwatched filter matches shows with any unwatched episode.
            unplayed=plays == 0
            if movie
            else (metadata.get("viewedLeafCount") or 0) < leaves,
            in_progress=(metadata.get("viewOffset") or 0) > 0
            if movie
            else 0 < (metadata.get("viewedLeafCount") or 0) < leaves,
            release_date=metadata.get("originallyAvailableAt") or None,
            server_added_at=parse_utc_datetime(metadata.get("addedAt")),
            server_updated_at=parse_utc_datetime(metadata.get("updatedAt")),
        )

    @override
    async def _iter_items(
        self, library_ids: list[str] | None, since: datetime | None
    ) -> AsyncIterator[list[ServerItem]]:
        """Normalize bounded pages; shows get details in one request per page.

        A poll drops unchanged items first, so it reads the details of the
        shows it reports and no others.
        """
        machine_id = await self.client.get_machine_identifier()
        plex_base = await self.client.base_url()
        for section in await self.select_sections(library_ids):
            async for page in self.client.iter_section_items(section.key):
                batch = [
                    item
                    for item in (
                        self._to_server_item(
                            metadata,
                            media_type=section.media_type,
                            section_key=section.key,
                            plex_base=plex_base,
                            machine_id=machine_id,
                        )
                        for metadata in page
                    )
                    if self.changed_since(item, since)
                ]
                if not batch:
                    continue
                if section.media_type is MediaType.SHOW:
                    await self._fill_show_details(batch, plex_base)
                yield batch

    @override
    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        """Unlock the fields holding *unlock*, then refresh the item.

        Plex locks a field once it is edited or deleted, and a refresh leaves a
        locked field as it is, so only the fields being fixed are unlocked.
        """
        await self.client.refresh_item(
            item_id, unlock={_PLEX_ASSET_FIELD[asset] for asset in unlock}
        )

    @override
    async def build_item_link(self, server_item_id: str) -> str:
        """Return a Plex web link for a metadata rating key."""
        return self._item_link(
            server_item_id, await self.client.get_machine_identifier()
        )

    @override
    async def _image_request(
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
    ) -> ProviderImageRequest:
        """Return a Plex image request, through the transcoder when sized."""
        plex_base = await self.client.base_url()
        path = f"/library/metadata/{server_item_id}/{_art_field(art_type)}"
        headers = self.client.auth_headers
        if size is None:
            return ProviderImageRequest(url=f"{plex_base}{path}", headers=headers)
        # The transcoder fills a box, so it gets the slot's shape (16:9 or 2:3).
        return ProviderImageRequest(
            url=f"{plex_base}/photo/:/transcode",
            headers=headers,
            params={
                "url": path,
                "width": str(art_type.display_width),
                "height": str(art_type.display_height),
                "minSize": "1",
                "upscale": "0",
            },
        )

    @override
    async def get_active_art_url(self, server_id: str, art_type: ArtType) -> str | None:
        """Return the currently selected Plex artwork URL."""
        return await self.client.get_art_url(server_id, _art_field(art_type))

    @override
    async def delete_theme(self, server_item_id: str, theme_id: str | None) -> None:
        """Delete the Plex theme attached to an item."""
        await self.client.delete_theme(server_item_id)

    @override
    async def list_collections(self) -> list[ServerCollection]:
        """Return the collections of every movie and show library."""
        machine_id = await self.client.get_machine_identifier()
        return [
            await self._server_collection(item, section, machine_id)
            for section in await self.get_sections()
            for item in await self.client.get_collections(section.key)
        ]

    async def _server_collection(
        self, item: PlexMetadata, section: ServerSection, machine_id: str | None
    ) -> ServerCollection:
        rating_key = str(item["ratingKey"])
        thumb, art, theme = item.get("thumb"), item.get("art"), item.get("theme")
        raw_smart = item.get("smart")
        is_smart = str(raw_smart) in {"1", "true", "True"}
        return ServerCollection(
            id=rating_key,
            title=item.get("title") or "",
            member_ids=tuple(await self.client.get_collection_member_ids(rating_key)),
            server_link=plex_web_link(
                "collections", rating_key, machine_id, app_config=self._app_config
            ),
            media_type=section.media_type,
            library_id=section.key,
            summary=item.get("summary") or None,
            sort_title=item.get("titleSort") or None,
            smart=is_smart,
            collection_mode=_PLEX_COLLECTION_MODES.get(
                str(item.get("collectionMode", "-1"))
            ),
            order_type=_PLEX_COLLECTION_ORDERS.get(
                str(item.get("collectionSort", "0"))
            ),
            collection_filtering=_PLEX_COLLECTION_FILTERING.get(
                str(item.get("collectionFilterBasedOnUser", "0"))
            ),
            thumb_url=await self.client.asset_url(thumb) if thumb else None,
            art_url=await self.client.asset_url(art) if art else None,
            theme_id=str(theme) if theme else None,
            added_at=parse_utc_datetime(item.get("addedAt")),
        )

    @override
    async def upload_collection_theme(
        self, server_item_id: str, mp3_bytes: bytes
    ) -> str:
        """Upload an MP3 as a Plex collection theme."""
        return await self.client.upload_collection_theme(server_item_id, mp3_bytes)

    @override
    async def delete_collection_theme(self, server_item_id: str) -> None:
        """Delete a Plex collection theme."""
        await self.client.delete_collection_theme(server_item_id)

    @override
    async def create_collection(
        self, section_key: str, title: str, media_type: MediaType, member_ids: list[str]
    ) -> ServerCollection:
        item = await self.client.create_collection(
            section_key, title, media_type, member_ids
        )
        section = ServerSection(key=section_key, title="", media_type=media_type)
        return await self._server_collection(
            item, section, await self.client.get_machine_identifier()
        )

    @override
    async def create_smart_collection(
        self,
        section_key: str,
        title: str,
        media_type: MediaType,
        filter_query: str,
    ) -> ServerCollection:
        item = await self.client.create_smart_collection(
            section_key, title, media_type, filter_query
        )
        section = ServerSection(key=section_key, title="", media_type=media_type)
        return await self._server_collection(
            item, section, await self.client.get_machine_identifier()
        )

    @override
    async def update_smart_collection_filter(
        self,
        server_collection_id: str,
        section_key: str,
        media_type: MediaType,
        filter_query: str,
    ) -> None:
        await self.client.update_smart_collection_filter(
            server_collection_id, section_key, media_type, filter_query
        )

    @override
    async def filter_choices(
        self, section_key: str, media_type: MediaType, field: str
    ) -> list[tuple[str, str]]:
        return await self.client.get_filter_choices(section_key, media_type, field)

    @override
    async def sync_item_labels(
        self,
        section_key: str,
        media_type: MediaType,
        label: str,
        *,
        add_ids: list[str],
        remove_ids: list[str],
    ) -> None:
        await self.client.sync_item_labels(
            section_key,
            media_type,
            label,
            add_ids=add_ids,
            remove_ids=remove_ids,
        )

    @override
    async def delete_collection(self, server_collection_id: str) -> None:
        await self.client.delete_collection(server_collection_id)

    @override
    async def update_collection_details(
        self,
        server_collection_id: str,
        *,
        title: str,
        summary: str | None,
        sort_title: str | None,
        mode: CollectionMode,
        order: CollectionOrder,
        visible_home: bool,
        visible_shared: bool = False,
        visible_library: bool = False,
        filtering: CollectionFiltering | None = None,
    ) -> None:
        await self.client.update_collection_details(
            server_collection_id,
            title=title,
            summary=summary,
            sort_title=sort_title,
            mode=mode,
            order=order,
            visible_home=visible_home,
            visible_shared=visible_shared,
            visible_library=visible_library,
            filtering=filtering,
        )

    @override
    async def get_collection_member_ids(self, server_collection_id: str) -> list[str]:
        return await self.client.get_collection_member_ids(server_collection_id)

    @override
    async def set_collection_members(
        self,
        server_collection_id: str,
        server_item_ids: list[str],
        *,
        order: CollectionOrder,
        append: bool = False,
    ) -> list[str]:
        return await self.client.set_collection_members(
            server_collection_id, server_item_ids, order, append=append
        )

    @override
    async def upload_collection_art(
        self,
        server_collection_id: str,
        art_type: ArtType,
        image_bytes: bytes,
        mime_type: str,
    ) -> None:
        await self.client.upload_collection_art(
            server_collection_id, art_type, image_bytes, mime_type
        )
