"""Delete the art and theme files Overture manages, and the server's copies of them.

Removing an asset can forget its selection, delete its file and delete the
media server's copy, in any combination. This module owns the two deletions
and says what each choice would change; the services that own a selection
forget it. Overture only ever deletes images and MP3 themes:
:meth:`AssetStorage.delete_file` checks every file it deletes, and the server
is only asked to delete images and theme songs.
"""

lazy from collections.abc import Sequence
lazy from pathlib import Path

lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..db.session import Database
lazy from ..domain import ArtType, ServerAsset
lazy from ..media_servers.adapters import FolderThemes, NoCollectionThemes, UploadThemes
lazy from ..media_servers.registry import ProviderRegistry
lazy from ..repositories.removal import RemovalCounts, RemovalRepository
lazy from ..schemas.removal import (
    ItemArtAsset,
    RemovalOption,
    RemovalOptions,
    RemovalTarget,
)
lazy from ..utils.assets import THEME_FILENAME
lazy from ..utils.errors import PublicServiceError
lazy from .storage.assets import AssetStorage

#: The item art slots each removable asset names.
ITEM_ART: frozendict[ItemArtAsset, tuple[ArtType, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        **{art_type: (art_type,) for art_type in ArtType},
        "art": tuple(ArtType),
    }
)

#: Why collection art has no file to delete.
NO_COLLECTION_ART_FILE = (
    "Overture keeps no file of collection art: the media server holds it"
)


def _option(count: int, unavailable: str | None, none: str) -> RemovalOption:
    """An option changing *count* records, or why it can change none."""
    if unavailable is None and count == 0:
        unavailable = none
    return RemovalOption(count=0 if unavailable else count, unavailable=unavailable)


def _options(
    counts: RemovalCounts,
    *,
    file_unavailable: str | None = None,
    server_unavailable: str | None = None,
) -> RemovalOptions:
    return RemovalOptions(
        forget=_option(counts.selected, None, "Nothing is selected"),
        delete_file=_option(counts.files, file_unavailable, "There is no local file"),
        delete_from_server=_option(
            counts.on_server, server_unavailable, "The media server has no copy"
        ),
    )


class AssetRemover:
    """Delete managed asset files and the server's copies, and say what would go."""

    def __init__(
        self,
        *,
        asset_storage: AssetStorage,
        provider_registry: ProviderRegistry,
        database: Database,
    ) -> None:
        self._storage = asset_storage
        self._providers = provider_registry
        self._database = database

    async def options(self, target: RemovalTarget) -> RemovalOptions:
        """Say what each removal choice would change for *target*, as things stand."""
        async with self._database.read_session() as session:
            repo = RemovalRepository(session)
            if target.item_ids:
                if target.asset == "theme":
                    return _options(await repo.item_themes(target.item_ids))
                return _options(
                    await repo.item_art(
                        target.item_ids, ITEM_ART[target.asset], target.season_id
                    ),
                    server_unavailable=self.art_deletion_unavailable,
                )
            if target.asset == "theme":
                return _options(
                    await repo.collection_themes(target.collection_ids),
                    file_unavailable=self._collection_theme_file_unavailable(),
                    server_unavailable=self._collection_theme_server_unavailable(),
                )
            return _options(
                await repo.collection_art(
                    target.collection_ids,
                    [art for art in ITEM_ART[target.asset] if not art.owned_by_season],
                ),
                file_unavailable=NO_COLLECTION_ART_FILE,
                server_unavailable=self.art_deletion_unavailable,
            )

    @property
    def art_deletion_unavailable(self) -> str | None:
        """Why the media server cannot delete artwork, or ``None`` when it can."""
        return self._providers.provider.art_deletion_unavailable

    def _collection_theme_file_unavailable(self) -> str | None:
        support = self._providers.provider.collections
        if isinstance(support, NoCollectionThemes):
            return "Emby keeps no collection themes"
        if isinstance(support, UploadThemes):
            return "Plex keeps collection themes itself: delete it from the server"
        return None

    def _collection_theme_server_unavailable(self) -> str | None:
        support = self._providers.provider.collections
        if isinstance(support, NoCollectionThemes):
            return "Emby keeps no collection themes"
        if isinstance(support, FolderThemes):
            return (
                "Jellyfin plays the theme from the collection's folder: delete the file"
            )
        return None

    def require_art_deletion(self) -> None:
        """Refuse a removal the server's API cannot carry out.

        Raises:
            PublicServiceError: 409 when the server cannot delete artwork.
        """
        if (reason := self.art_deletion_unavailable) is not None:
            raise PublicServiceError(409, reason)

    async def delete_item_art_files(
        self, item: MediaItem, owners: Sequence[MediaItem | Season], art_type: ArtType
    ) -> list[MediaItem | Season]:
        """Delete each owner's local file of *art_type*; return those that had one."""
        if item.folder_path is None:
            return []
        deleted: list[MediaItem | Season] = []
        for owner in owners:
            path = self._storage.find_local_art_path(
                art_type, item=item, season=owner if isinstance(owner, Season) else None
            )
            if path is not None and await self._storage.delete_file_async(
                path, item.folder_path
            ):
                deleted.append(owner)
        return deleted

    async def delete_item_theme_file(self, item: MediaItem) -> bool:
        """Delete the item's local theme; return whether it had one."""
        path = self._storage.local_theme_path(item)
        return (
            path is not None
            and item.folder_path is not None
            and await self._storage.delete_file_async(path, item.folder_path)
        )

    async def delete_item_art_on_server(
        self, owners: Sequence[MediaItem | Season], art_type: ArtType
    ) -> None:
        """Delete the server's image of *art_type* for each owner it holds.

        Raises:
            PublicServiceError: 409 when the server cannot delete artwork.
        """
        self.require_art_deletion()
        for owner in owners:
            if owner.server_item_id is not None:
                await self._providers.provider.delete_art(
                    owner.server_item_id, art_type
                )

    async def delete_item_theme_on_server(self, item: MediaItem) -> None:
        """Delete the theme songs the server plays for the item."""
        if (server_id := item.server_item_id) is None:
            return
        provider = self._providers.provider
        for theme in await provider.get_theme_songs(server_id):
            # Deleting a Jellyfin or Emby theme song deletes its file.
            if theme.path is not None and not theme.path.lower().endswith(".mp3"):
                continue
            await provider.delete_theme(server_id, theme.id)

    async def refresh_item(self, item: MediaItem, assets: set[ServerAsset]) -> None:
        """Have the server read the item again after local files of *assets* went."""
        if assets and item.server_item_id is not None:
            await self._providers.provider.refresh_item(
                item.server_item_id, unlock=assets
            )

    async def delete_collection_art(
        self, row: MediaCollection, art_type: ArtType
    ) -> None:
        """Delete the collection's image from every server copy.

        Raises:
            PublicServiceError: 409 when the server cannot delete artwork.
        """
        self.require_art_deletion()
        for server_id in row.server_ids:
            await self._providers.provider.delete_art(server_id, art_type)

    async def delete_collection_theme(self, row: MediaCollection) -> None:
        """Delete the theme Plex keeps for each of the collection's copies.

        Raises:
            PublicServiceError: 409 when the server keeps no themes to delete.
        """
        if reason := self._collection_theme_server_unavailable():
            raise PublicServiceError(409, reason)
        for server_id in row.server_ids:
            await self._providers.provider.delete_collection_theme(server_id)

    async def delete_collection_theme_file(self, folder: Path, root: Path) -> bool:
        """Delete the theme file Jellyfin plays from the collection's folder.

        Raises:
            PublicServiceError: 409 when the server keeps no theme files.
        """
        if reason := self._collection_theme_file_unavailable():
            raise PublicServiceError(409, reason)
        return await self._storage.delete_file_async(folder / THEME_FILENAME, str(root))
