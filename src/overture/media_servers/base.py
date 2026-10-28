"""Shared media-server provider base implementation."""

lazy from abc import ABC, abstractmethod
lazy from collections.abc import AsyncIterator, Collection, Mapping, Sequence
lazy from datetime import datetime
lazy from typing import ClassVar

lazy from ..config import Settings
lazy from ..db.models.media_item import MediaItem
lazy from ..domain import (
    ArtType,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    ImageSize,
    MediaType,
    ServerAsset,
    ServerType,
    media_sort_key,
)
lazy from ..schemas.art import ArtCandidate
lazy from .adapters import (
    CollectionSupport,
    ProviderImageRequest,
    ServerCollection,
    ServerItem,
    ServerSection,
    ServerTheme,
)
lazy from .http_client import MediaServerHttpClient


class BaseMediaServerProvider[C: MediaServerHttpClient](ABC):
    """Adapt one media server's API to the operations Overture relies on.

    The provider owns its HTTP client; everything the client already answers
    the same way on every server is implemented once here.
    """

    server_type: ClassVar[ServerType]
    collections: ClassVar[CollectionSupport | None] = None

    async def list_collections(self) -> list[ServerCollection]:
        """Return collections when the provider declares support."""
        return []

    async def create_collection(
        self, section_key: str, title: str, media_type: MediaType, member_ids: list[str]
    ) -> ServerCollection:
        """Create a collection with initial membership."""
        raise NotImplementedError

    async def create_smart_collection(
        self,
        section_key: str,
        title: str,
        media_type: MediaType,
        filter_query: str,
    ) -> ServerCollection:
        """Create a smart collection backed by a server filter query."""
        raise NotImplementedError

    async def update_smart_collection_filter(
        self,
        server_collection_id: str,
        section_key: str,
        media_type: MediaType,
        filter_query: str,
    ) -> None:
        """Update the server filter query of an existing smart collection."""
        raise NotImplementedError

    async def filter_choices(
        self, section_key: str, media_type: MediaType, field: str
    ) -> list[tuple[str, str]]:
        """List the keys and names a smart filter field accepts in a section."""
        raise NotImplementedError

    async def smart_collection_filter(self, server_collection_id: str) -> str:
        """Return the filter query a smart collection made on the server keeps."""
        raise NotImplementedError

    async def find_matching(
        self, section_key: str, media_type: MediaType, filter_query: str, size: int
    ) -> tuple[int, list[str]]:
        """How many items a smart filter matches, and the first *size* IDs."""
        raise NotImplementedError

    async def order_collection_hubs(
        self, section_key: str, server_collection_ids: Sequence[str]
    ) -> None:
        """Order promoted collections' Home rows, first to last."""
        raise NotImplementedError

    async def sync_item_labels(
        self,
        section_key: str,
        media_type: MediaType,
        label: str,
        *,
        add: Mapping[str, Sequence[str]],
        remove_ids: list[str],
    ) -> None:
        """Add and remove a managed label on library items."""
        raise NotImplementedError

    async def delete_collection(self, server_collection_id: str) -> None:
        """Delete a collection without deleting its media."""
        raise NotImplementedError

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
        """Update collection metadata and supported display options."""
        raise NotImplementedError

    async def get_collection_member_ids(self, server_collection_id: str) -> list[str]:
        """Read current membership before applying append thresholds."""
        raise NotImplementedError

    async def set_collection_members(
        self,
        server_collection_id: str,
        server_item_ids: list[str],
        *,
        order: CollectionOrder,
        append: bool = False,
    ) -> list[str]:
        """Apply a membership diff, then the supported member order."""
        raise NotImplementedError

    async def upload_collection_art(
        self,
        server_collection_id: str,
        art_type: ArtType,
        image_bytes: bytes,
        mime_type: str,
    ) -> None:
        """Upload already validated artwork bytes."""
        raise NotImplementedError

    async def upload_collection_theme(
        self, server_item_id: str, mp3_bytes: bytes
    ) -> str:
        """Upload a theme on a provider declaring UploadThemes."""
        raise NotImplementedError("Collection theme uploads are unsupported")

    async def delete_collection_theme(self, server_item_id: str) -> None:
        """Delete a theme on a provider declaring UploadThemes."""
        raise NotImplementedError("Collection theme uploads are unsupported")

    def __init__(self, *, client: C, app_config: Settings) -> None:
        self.client = client
        self._app_config = app_config

    async def get_sections(self) -> list[ServerSection]:
        """Return the movie and show libraries, movies first, then by title."""
        return sorted(
            await self._list_sections(),
            key=lambda section: media_sort_key(
                section.media_type, section.title, section.key
            ),
        )

    async def select_sections(
        self, library_ids: Collection[str] | None
    ) -> list[ServerSection]:
        """Return the libraries *library_ids* names, or every one without a filter."""
        sections = await self.get_sections()
        if not library_ids:
            return sections
        wanted = set(library_ids)
        return [section for section in sections if section.key in wanted]

    @abstractmethod
    async def _list_sections(self) -> list[ServerSection]:
        """Return the server's movie and show libraries."""

    def iter_items(
        self, library_ids: list[str] | None = None
    ) -> AsyncIterator[list[ServerItem]]:
        """Yield bounded provider pages for a complete listing."""
        return self._iter_items(library_ids, None)

    def iter_items_since(
        self, since: datetime, library_ids: list[str] | None = None
    ) -> AsyncIterator[list[ServerItem]]:
        """Yield bounded pages of the items added or updated after *since*."""
        return self._iter_items(library_ids, since)

    @abstractmethod
    def _iter_items(
        self, library_ids: list[str] | None, since: datetime | None
    ) -> AsyncIterator[list[ServerItem]]:
        """Yield listing pages, keeping only items changed after *since*.

        Implementations filter before reading a show's seasons, so a poll
        asks the server for details of the shows it reports and no others.
        """

    @staticmethod
    def changed_since(item: ServerItem, since: datetime | None) -> bool:
        """Return whether *item* was added or updated after *since*."""
        if since is None:
            return True
        times = [t for t in (item.server_updated_at, item.server_added_at) if t]
        return bool(times) and max(times) > since

    async def get_directors(self, server_item_ids: list[str]) -> dict[str, str | None]:
        """Return directors of movies listed with a ``director_etag``.

        Servers that list a movie's director with the movie never set the
        etag, so there is nothing to fetch.
        """
        return {}

    async def find_item_id(self, item: MediaItem) -> str | None:
        """Find a media-server item ID for a local DB item."""
        return await self.client.find_item_id(item)

    async def find_season_id(self, server_item_id: str, season_num: int) -> str | None:
        """Find a media-server season ID."""
        return await self.client.find_season_id(server_item_id, season_num)

    async def test_connection(self) -> bool:
        """Return whether the media server is reachable."""
        return await self.client.test_connection()

    @abstractmethod
    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        """Ask the media server to reload an item, unlocking *unlock* first.

        Only servers that lock edited fields (Plex) act on *unlock*; a locked
        field keeps its current value through a refresh.
        """

    @abstractmethod
    async def build_item_link(self, server_item_id: str) -> str:
        """Return a provider web link for a media-server item."""

    @abstractmethod
    async def _image_request(
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
    ) -> ProviderImageRequest:
        """Return an authenticated image request, scaled to *size* if given."""

    async def build_provider_art_request(
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
    ) -> ProviderImageRequest:
        """Return request details for provider art, scaled to *size* if given."""
        return await self._image_request(server_item_id, art_type, size)

    async def build_collection_image_request(
        self,
        server_item_id: str,
        art_type: ArtType,
        size: ImageSize | None,
        *,
        current_url: str,
    ) -> ProviderImageRequest:
        """Return request details for a collection image, scaled to *size* if given.

        *current_url* is the image sync saw, for servers that address a
        collection's images by path rather than by item.
        """
        return await self._image_request(server_item_id, art_type, size)

    def get_download_headers(self, url: str) -> dict[str, str]:
        """Return the server's credentials, for its own trusted URLs only."""
        if self._app_config.is_trusted_media_server_url(url):
            return self.client.auth_headers
        return {}

    @abstractmethod
    async def get_active_art_url(self, server_id: str, art_type: ArtType) -> str | None:
        """Return the currently selected provider artwork URL."""

    async def get_art_candidates(
        self, server_id: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        """Return provider artwork candidates."""
        return await self.client.get_art_candidates(server_id, art_type)

    async def get_theme_songs(self, server_item_id: str) -> list[ServerTheme]:
        """Return provider theme song metadata."""
        return await self.client.get_theme_songs(server_item_id)

    @abstractmethod
    async def delete_theme(self, server_item_id: str, theme_id: str | None) -> None:
        """Delete an item's theme song."""

    async def close(self) -> None:
        """Close the owned HTTP client."""
        await self.client.close()
