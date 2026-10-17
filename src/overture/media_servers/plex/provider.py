"""Plex media-server adapter."""

lazy from collections.abc import AsyncIterator, Collection
lazy from datetime import datetime
lazy from typing import Any, ClassVar, Literal, override

lazy from ...config import Settings
lazy from ...domain import ArtType, ImageSize, MediaType, ServerAsset, ServerType
lazy from ...utils.security import remove_sensitive_url_params
lazy from ...utils.time import parse_utc_datetime
lazy from ..adapters import (
    MAX_SEASONS_PER_SHOW,
    ProviderImageRequest,
    ServerItem,
    ServerSeason,
    ServerSection,
    server_path,
)
lazy from ..base import BaseMediaServerProvider
lazy from ..errors import MediaServerError
lazy from ..wire import PlexMetadata
lazy from .client import PlexClient, plex_web_link

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


def _art_field(art_type: ArtType) -> Literal["thumb", "art"]:
    """Return the Plex field that holds *art_type*."""
    return "art" if art_type is ArtType.BACKGROUND else "thumb"


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
        width = art_type.display_width
        height = width * 9 // 16 if art_type is ArtType.BACKGROUND else width * 3 // 2
        return ProviderImageRequest(
            url=f"{plex_base}/photo/:/transcode",
            headers=headers,
            params={
                "url": path,
                "width": str(width),
                "height": str(height),
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

    async def list_collections(self, media_type: MediaType) -> list[dict[str, Any]]:
        """Return Plex collections for all matching library sections."""
        results: list[dict[str, Any]] = []
        for section in await self.get_sections():
            if section.media_type is not media_type:
                continue
            collections = await self.client.get_collections(section.key)
            for collection in collections:
                collection["media_type"] = media_type
                collection["server_type"] = self.server_type
            results.extend(collections)
        return results

    async def upload_collection_theme(
        self, server_item_id: str, mp3_bytes: bytes
    ) -> str:
        """Upload an MP3 as a Plex collection theme."""
        return await self.client.upload_collection_theme(server_item_id, mp3_bytes)

    async def verify_collection_theme(
        self, server_item_id: str, file_hash: str
    ) -> str | None:
        """Return the theme version when the active theme has *file_hash*."""
        return await self.client.verify_collection_theme(server_item_id, file_hash)

    async def delete_collection_theme(self, server_item_id: str) -> None:
        """Delete a Plex collection theme."""
        await self.client.delete_collection_theme(server_item_id)
