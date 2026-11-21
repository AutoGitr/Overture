"""A collection's theme: its status, queuing a new one and removing it."""

lazy from pathlib import Path

lazy from ...db.ledger import (
    Destination,
    Evidence,
    clear_selection,
    observe,
    read_asset,
    record_file,
    select_theme,
)
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...domain import AssetScope, DeliveryChannel, ServerAsset, ThemeIdSource
lazy from ...media_servers.registry import CollectionProvider
lazy from ...schemas.assets import AssetRead, asset_read
lazy from ...schemas.collections import (
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
    SetCollectionThemeResponse,
)
lazy from ...schemas.common import Status
lazy from ...schemas.removal import AssetRemoval
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..downloads.collection_theme import (
    collection_theme_unavailable,
    collection_themes_unavailable,
    folder_lacks_theme,
    theme_folders,
)
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..removal import AssetRemover
lazy from ..themes.youtube_resolver import DownloadError
lazy from .access import CollectionAccess
lazy from .destinations import collection_destinations


class CollectionThemes:
    """Queue, report and remove the themes of managed collections."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        downloads: DownloadService,
        remover: AssetRemover,
    ) -> None:
        self._remover = remover
        self._access = access
        self._downloads = downloads

    def unavailable(self) -> str | None:
        """Why no configured server can take collection themes, if none can."""
        return collection_themes_unavailable(
            self._access.provider_registry.collection_providers()
        )

    async def folder_lacks_theme(self, row: MediaCollection) -> bool:
        """Whether a Jellyfin folder of the collection holds no theme file."""
        return await folder_lacks_theme(row, self._access.provider_registry)

    async def status(self, collection_id: int) -> AssetRead:
        """Return the current theme status for a collection."""
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id)
        return asset_read(read_asset(row, ServerAsset.THEME))

    async def queue(
        self, collection_id: int, body: SetCollectionThemeRequest
    ) -> SetCollectionThemeResponse:
        """Queue a YouTube track to become the theme of a collection.

        An inactive collection has no server copy to hold it, so the choice is
        kept and the sync that puts the collection back downloads it.
        """
        reason = self.unavailable()
        if reason is not None:
            raise PublicServiceError(400, reason)
        async with self._access.database.read_session() as session:
            row = await self._access.require_managed(session, collection_id)
        theme = asset_read(read_asset(row, ServerAsset.THEME))
        if not row.copies:
            return await self._keep(collection_id, body.youtube_id)
        target = JobTarget.collection_theme(collection_id, row.title, body.youtube_id)
        async with self._access.asset_locks.acquire(target.slot.lock_key):
            reason = await collection_theme_unavailable(
                row, provider_registry=self._access.provider_registry
            )
            if reason:
                raise PublicServiceError(400, reason)
            async with self._access.database.write_session() as session:
                await self._access.require(session, collection_id)
                job_id, _ = await self._downloads.queue_job(session, target)
        await self._downloads.committed(session)
        return SetCollectionThemeResponse(job_id=job_id, theme=theme)

    async def _keep(
        self, collection_id: int, youtube_id: str
    ) -> SetCollectionThemeResponse:
        """Record the theme an inactive collection gets once it is on the server."""
        scope = AssetScope(collection_id=collection_id)
        async with (
            self._access.asset_locks.acquire(scope.lock_key),
            self._access.database.write_session() as db,
        ):
            row = await self._access.require_managed(db, collection_id)
            theme = asset_read(
                select_theme(
                    row,
                    youtube_id,
                    source=ThemeIdSource.SELECTION,
                    title=None,
                    duration=None,
                )
            )
            row.updated_at = utc_now()
            db.add(row)
            await self._downloads.cancel_assets(db, scope)
        await self._downloads.committed(db)
        await self._access.updated(collection_id)
        return SetCollectionThemeResponse(job_id=None, theme=theme)

    async def remove(
        self, collection_id: int, removal: AssetRemoval
    ) -> DeleteCollectionThemeResponse:
        """Forget a collection's theme, delete the server's copy or its file.

        Plex keeps the themes uploaded to it; Jellyfin plays the file in the
        collection's folder.

        Raises:
            PublicServiceError: 409 when the server keeps no theme that way.
        """
        async with self._access.database.read_session() as session:
            row = await self._access.require_managed(session, collection_id)
        scope = AssetScope(collection_id=collection_id)
        async with self._access.asset_locks.acquire(scope.lock_key):
            if removal.delete_from_server:
                await self._remover.delete_collection_theme(row)
            deleted = await self._delete_files(row) if removal.delete_file else []
            async with self._access.database.write_session() as db:
                row = await self._access.require_managed(db, collection_id)
                now = utc_now()
                if removal.forget:
                    clear_selection(row, ServerAsset.THEME)
                    await self._downloads.cancel_assets(db, scope)
                if removal.delete_from_server:
                    for destination in collection_destinations(
                        row, ServerAsset.THEME, self._access.provider_registry
                    ):
                        if destination.channel is DeliveryChannel.UPLOAD:
                            observe(
                                row,
                                ServerAsset.THEME,
                                destination,
                                Evidence.DIFFERENT,
                                ref=None,
                                at=now,
                            )
                for destination, _, _, _ in deleted:
                    record_file(
                        row, ServerAsset.THEME, None, destination=destination, at=now
                    )
                row.updated_at = now
                db.add(row)
                theme = asset_read(read_asset(row, ServerAsset.THEME))
            await self._downloads.committed(db)
            for _, provider, part, _ in deleted:
                await provider.refresh_item(part.server_item_id or "", unlock=())
        await self._access.updated(collection_id)
        return DeleteCollectionThemeResponse(status=Status.OK, theme=theme)

    async def _delete_files(
        self, row: MediaCollection
    ) -> list[tuple[Destination, CollectionProvider, CollectionLibrary, Path]]:
        """Delete the theme file in each Jellyfin server's folder for the collection.

        Returns the folders that had one.

        Raises:
            PublicServiceError: 400 when a server's folder cannot be used.
        """
        try:
            folders = await theme_folders(row, self._access.provider_registry)
        except DownloadError as exc:
            raise PublicServiceError(400, str(exc)) from exc
        return [
            (destination, provider, part, folder)
            for destination, provider, part, folder in folders
            if provider.server.collections_path is not None
            and await self._remover.delete_collection_theme_file(
                folder, provider.server.collections_path
            )
        ]
