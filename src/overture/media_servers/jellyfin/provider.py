"""Jellyfin media-server adapter and the MediaBrowser behaviour Emby shares."""

lazy from collections.abc import AsyncIterator, Collection
lazy from datetime import datetime
lazy from typing import ClassVar, override

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
lazy from ...utils.time import parse_utc_datetime
lazy from ..adapters import (
    MAX_SEASONS_PER_SHOW,
    FolderThemes,
    ProviderImageRequest,
    ServerCollection,
    ServerItem,
    ServerSeason,
    ServerSection,
    server_path,
    video_resolution,
)
lazy from ..base import BaseMediaServerProvider
lazy from ..errors import MediaServerError
lazy from ..health import MediaServerHealthTracker
lazy from ..wire import MediaBrowserItem, MediaBrowserPerson
lazy from .client import (
    COLLECTION_TYPES,
    IMAGE_TYPES,
    ITEM_TYPES,
    JellyfinClient,
    provider_ids,
)

#: The media type each supported library collection type holds.
_COLLECTION_MEDIA_TYPES = frozendict(
    {collection: media_type for media_type, collection in COLLECTION_TYPES.items()}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


def _media_browser_image_url(
    client: JellyfinClient,
    item_id: str,
    kind: str,
    tag: str | None,
) -> str | None:
    """Return an image URL for a MediaBrowser item, when one exists."""
    if not tag:
        return None
    return client.api_url(f"/Items/{item_id}/Images/{kind}", tag=tag)


def _media_browser_person(
    people: list[MediaBrowserPerson], person_type: str
) -> str | None:
    """Return the first person credited with a MediaBrowser person type."""
    return next(
        (person.get("Name") for person in people if person.get("Type") == person_type),
        None,
    )


def _media_browser_item_folder(
    metadata: MediaBrowserItem, media_type: MediaType
) -> str | None:
    """Return the artwork directory represented by a MediaBrowser item path."""
    raw_path = metadata.get("Path")
    if not raw_path:
        return None

    path = str(raw_path)
    if media_type is not MediaType.MOVIE or metadata.get("IsFolder", False):
        return path
    return str(server_path(path).parent)


class MediaBrowserProvider[C: JellyfinClient](BaseMediaServerProvider[C]):
    """Adapt MediaBrowser (Jellyfin and Emby) responses to the shared contract."""

    def _server_season(self, season: MediaBrowserItem, file_count: int) -> ServerSeason:
        """Normalize one season row with its counted episodes."""
        season_id = season["Id"]
        season_num = int(season.get("IndexNumber", 0) or 0)
        return ServerSeason(
            num=season_num,
            title=season.get("Name") or f"Season {season_num}",
            file_count=file_count,
            server_item_id=season_id,
            poster_url=_media_browser_image_url(
                self.client,
                season_id,
                "Primary",
                (season.get("ImageTags") or {}).get("Primary", ""),
            ),
        )

    async def _seasons_by_show(self, parent_id: str) -> dict[str, list[ServerSeason]]:
        """Read the seasons under a library or one show, grouped by show.

        One listing covers every season under *parent_id* and one more counts
        its episodes: without a user the servers omit season child counts.
        """
        rows: dict[str, list[MediaBrowserItem]] = {}
        seen: set[str] = set()
        async for page in self.client.iter_seasons(parent_id):
            for season in page:
                show_id = season.get("SeriesId")
                if not show_id or season["Id"] in seen:
                    raise MediaServerError(
                        "Media server returned an invalid season listing"
                    )
                seen.add(season["Id"])
                show_seasons = rows.setdefault(show_id, [])
                if len(show_seasons) >= MAX_SEASONS_PER_SHOW:
                    raise MediaServerError("Media server returned too many seasons")
                show_seasons.append(season)
        if not rows:
            return {}
        counts = await self.client.count_episodes_by_season(parent_id)
        return {
            show_id: [
                self._server_season(season, counts[season["Id"]])
                for season in show_seasons
            ]
            for show_id, show_seasons in rows.items()
        }

    def _to_server_item(
        self,
        metadata: MediaBrowserItem,
        *,
        media_type: MediaType,
        section_id: str,
    ) -> ServerItem:
        """Normalize one item, without its seasons, into a ServerItem."""
        item_id = metadata["Id"]
        studios = metadata.get("Studios") or []
        people = metadata.get("People") or []
        etag = metadata.get("Etag")
        movie = media_type is MediaType.MOVIE
        if movie and not etag:
            raise MediaServerError("Media server returned a movie without an Etag")
        community_rating = metadata.get("CommunityRating")
        critic_rating = metadata.get("CriticRating")
        runtime_ticks = metadata.get("RunTimeTicks")
        return ServerItem(
            id=item_id,
            title=metadata.get("Name") or "",
            year=metadata.get("ProductionYear"),
            media_type=media_type,
            guids=provider_ids(metadata),
            poster_url=_media_browser_image_url(
                self.client,
                item_id,
                "Primary",
                (metadata.get("ImageTags") or {}).get("Primary", ""),
            ),
            background_url=(
                f"{self.client.api_base_url}/Items/{item_id}/Images/Backdrop"
                if metadata.get("BackdropImageTags", [])
                else None
            ),
            server_link=self.server_link(item_id),
            library_id=section_id,
            folder_path=_media_browser_item_folder(metadata, media_type),
            director_etag=etag if movie else None,
            studio=studios[0].get("Name") if studios else None,
            genres=tuple(metadata.get("Genres") or []),
            actors=tuple(
                name
                for person in people
                if person.get("Type") == "Actor" and (name := person.get("Name"))
            ),
            writers=tuple(
                name
                for person in people
                if person.get("Type") == "Writer" and (name := person.get("Name"))
            ),
            producers=tuple(
                name
                for person in people
                if person.get("Type") == "Producer" and (name := person.get("Name"))
            ),
            countries=tuple(metadata.get("ProductionLocations") or []),
            labels=tuple(metadata.get("Tags") or ())
            or tuple(
                name
                for tag in metadata.get("TagItems") or ()
                if (name := tag.get("Name"))
            ),
            content_rating=metadata.get("OfficialRating") or None,
            resolution=video_resolution(metadata.get("Width")) if movie else None,
            # Critic ratings are percentages; Overture rates out of ten like Plex.
            critic_rating=float(critic_rating) / 10
            if isinstance(critic_rating, int | float)
            else None,
            audience_rating=float(community_rating)
            if isinstance(community_rating, int | float)
            else None,
            duration_minutes=int(runtime_ticks // 600_000_000)
            if isinstance(runtime_ticks, int) and runtime_ticks > 0
            else None,
            release_date=(metadata.get("PremiereDate") or "")[:10] or None,
            server_added_at=parse_utc_datetime(
                metadata.get("DateCreated"), naive_tz=self._app_config.tzinfo
            ),
            server_updated_at=parse_utc_datetime(
                metadata.get("DateLastMediaAdded") or metadata.get("DateModified"),
                naive_tz=self._app_config.tzinfo,
            ),
        )

    @override
    async def _list_sections(self) -> list[ServerSection]:
        """Return the server's movie and show libraries."""
        return [
            ServerSection(
                key=section["ItemId"],
                title=section.get("Name") or section["ItemId"],
                media_type=media_type,
            )
            for section in await self.client.get_sections()
            if (
                media_type := _COLLECTION_MEDIA_TYPES.get(
                    section.get("CollectionType") or ""
                )
            )
        ]

    @override
    async def _iter_items(
        self, library_ids: list[str] | None, since: datetime | None
    ) -> AsyncIterator[list[ServerItem]]:
        """Normalize validated section pages, reading seasons once per section.

        A full listing reads every season of a section in one listing; a poll
        reads the seasons of each changed show only.
        """
        for section in await self.select_sections(library_ids):
            show = section.media_type is MediaType.SHOW
            seasons = (
                await self._seasons_by_show(section.key)
                if show and since is None
                else {}
            )
            async for page in self.client.iter_section_items(
                section.key, ITEM_TYPES[section.media_type]
            ):
                batch = [
                    item
                    for item in (
                        self._to_server_item(
                            metadata,
                            media_type=section.media_type,
                            section_id=section.key,
                        )
                        for metadata in page
                    )
                    if self.changed_since(item, since)
                ]
                if show:
                    for item in batch:
                        if since is not None:
                            seasons = await self._seasons_by_show(item.id)
                        item.seasons = seasons.pop(item.id, [])
                if batch:
                    yield batch

    @override
    async def get_directors(self, server_item_ids: list[str]) -> dict[str, str | None]:
        """Return the first credited director of each listed movie."""
        return {
            item["Id"]: _media_browser_person(item.get("People") or [], "Director")
            for item in await self.client.get_people(server_item_ids)
        }

    @override
    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        """Refresh an item; MediaBrowser servers lock no fields a refresh replaces."""
        await self.client.refresh_item(item_id)

    @override
    async def build_item_link(self, server_item_id: str) -> str:
        """Return a web link for an item."""
        return self.server_link(server_item_id)

    def server_link(self, server_item_id: str) -> str:
        """Return a web link for an item."""
        return (
            f"{self.client.web_base_url}/web/index.html#!/details?id={server_item_id}"
        )

    @override
    async def _image_request(
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
    ) -> ProviderImageRequest:
        """Return an image request, scaled by the server when sized."""
        params = (
            {}
            if size is None
            else {"maxWidth": str(art_type.display_width), "quality": "90"}
        )
        return ProviderImageRequest(
            url=self.client.api_url(
                f"/Items/{server_item_id}/Images/{IMAGE_TYPES[art_type]}", **params
            ),
            headers=self.client.auth_headers,
        )

    @override
    async def get_active_art_url(self, server_id: str, art_type: ArtType) -> str | None:
        """Return the currently selected artwork URL."""
        return await self.client.get_active_image_url(server_id, art_type)

    @override
    async def delete_theme(self, server_item_id: str, theme_id: str | None) -> None:
        """Delete a theme song; MediaBrowser themes are items of their own."""
        if theme_id:
            await self.client.delete_item(theme_id)

    @override
    async def list_collections(self) -> list[ServerCollection]:
        """Return every BoxSet; Jellyfin keeps them outside the libraries."""
        results: list[ServerCollection] = []
        for boxset in await self.client.get_boxsets():
            boxset_id = boxset["Id"]
            tmdb_id = provider_ids(boxset).get("tmdb", "")
            results.append(
                ServerCollection(
                    id=boxset_id,
                    title=boxset.get("Name") or "",
                    member_ids=tuple(
                        await self.client.get_boxset_member_ids(boxset_id)
                    ),
                    server_link=self.server_link(boxset_id),
                    summary=boxset.get("Overview") or None,
                    thumb_url=_media_browser_image_url(
                        self.client,
                        boxset_id,
                        "Primary",
                        (boxset.get("ImageTags") or {}).get("Primary"),
                    ),
                    art_url=_media_browser_image_url(
                        self.client,
                        boxset_id,
                        "Backdrop",
                        next(iter(boxset.get("BackdropImageTags") or []), None),
                    ),
                    tmdb_id=int(tmdb_id) if tmdb_id.isdigit() else None,
                    path=boxset.get("Path"),
                    added_at=parse_utc_datetime(
                        boxset.get("DateCreated"), naive_tz=self._app_config.tzinfo
                    ),
                )
            )
        return results

    @override
    async def create_collection(
        self, section_key: str, title: str, media_type: MediaType, member_ids: list[str]
    ) -> ServerCollection:
        collection_id = await self.client.create_collection(title, member_ids)
        metadata = await self.client.get_item(collection_id)
        return ServerCollection(
            id=collection_id,
            title=title,
            member_ids=tuple(member_ids),
            server_link=await self.build_item_link(collection_id),
            library_id=section_key,
            media_type=media_type,
            path=metadata.get("Path"),
        )

    @override
    async def delete_collection(self, server_collection_id: str) -> None:
        await self.client.delete_item(server_collection_id)

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
        smart: bool,
        visible_home: bool,
        visible_shared: bool = False,
        visible_library: bool = False,
        filtering: CollectionFiltering | None = None,
    ) -> None:
        await self.client.update_collection_details(
            server_collection_id, title, summary, sort_title, order
        )

    @override
    async def get_collection_member_ids(self, server_collection_id: str) -> list[str]:
        return await self.client.get_boxset_member_ids(server_collection_id)

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
            server_collection_id, server_item_ids, append=append
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


class JellyfinProvider(MediaBrowserProvider[JellyfinClient]):
    """Adapt Jellyfin responses to the shared media-server contract."""

    server_type: ClassVar[ServerType] = ServerType.JELLYFIN
    collections = FolderThemes()

    def __init__(
        self,
        *,
        client: JellyfinClient | None = None,
        app_config: Settings,
        health: MediaServerHealthTracker | None = None,
    ) -> None:
        super().__init__(
            client=client or JellyfinClient(app_config=app_config, health=health),
            app_config=app_config,
        )
