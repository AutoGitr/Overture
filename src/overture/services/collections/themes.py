"""A collection's theme: its status, queuing a new one and removing it."""

lazy from pathlib import Path

lazy from ...config import Settings
lazy from ...db.completion import collection_theme_status
lazy from ...db.theme_file import record_theme_file
lazy from ...domain import AssetScope, MediaType
lazy from ...media_servers.adapters import UploadThemes
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
    collection_read,
    collection_theme_status_response,
)
lazy from ...schemas.common import EnqueuedJobResponse, Status
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..downloads.collection_theme import (
    collection_theme_unavailable,
    collection_themes_unavailable,
    theme_folder,
)
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..themes.youtube_resolver import DownloadError
lazy from .access import CollectionAccess


class CollectionThemes:
    """Queue, report and remove the themes of managed collections."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        downloads: DownloadService,
        app_config: Settings,
    ) -> None:
        self._access = access
        self._downloads = downloads
        self._app_config = app_config

    def unavailable(self) -> str | None:
        """Why this server cannot take collection themes, if it cannot."""
        return collection_themes_unavailable(self._access.provider(), self._app_config)

    async def status(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionThemeStatusResponse:
        """Return the current theme status for a collection."""
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id, media_type)
        return collection_theme_status_response(collection_read(row, None))

    async def queue(
        self, collection_id: int, body: SetCollectionThemeRequest
    ) -> EnqueuedJobResponse:
        """Queue a YouTube track to become the theme of a collection."""
        reason = self.unavailable()
        if reason is not None:
            raise PublicServiceError(400, reason)
        async with self._access.database.read_session() as session:
            row = await self._access.require_managed(
                session, collection_id, body.media_type
            )
        target = JobTarget.collection_theme(collection_id, row.title, body.youtube_id)
        async with self._access.asset_locks.acquire(target.slot.lock_key):
            reason = await collection_theme_unavailable(
                row, provider=self._access.provider(), app_config=self._app_config
            )
            if reason:
                raise PublicServiceError(400, reason)
            async with self._access.database.write_session() as session:
                await self._access.require(session, collection_id, body.media_type)
                job_id, _ = await self._downloads.queue_job(session, target)
        await self._downloads.committed(session)
        return EnqueuedJobResponse(job_id=job_id)

    async def delete(
        self, collection_id: int, media_type: MediaType
    ) -> DeleteCollectionThemeResponse:
        """Remove the theme from a collection and clear its stored record."""
        async with self._access.database.read_session() as session:
            await self._access.require_managed(session, collection_id, media_type)
        scope = AssetScope(collection_id=collection_id)
        async with self._access.asset_locks.acquire(scope.lock_key):
            await self._remove_server_theme(collection_id)
            async with self._access.database.write_session() as db:
                row = await CollectionRepository(db).get(collection_id, media_type)
                if row is not None:
                    row.sqlmodel_update(
                        {
                            "youtube_id": None,
                            "youtube_id_source": None,
                            "youtube_title": None,
                            "youtube_duration": None,
                            "server_theme_id": None,
                            "updated_at": utc_now(),
                        }
                    )
                    record_theme_file(row, None)
                    db.add(row)
                await self._downloads.cancel_assets(db, scope)
        await self._downloads.committed(db)

        cleared_status = collection_theme_status(
            server_has_theme=False, youtube_id=None
        )
        await self._access.broadcast(
            "collection.theme.updated",
            {
                "collection_id": collection_id,
                "media_type": media_type,
                "has_theme": False,
                "youtube_id": None,
                "youtube_title": None,
                "youtube_duration": None,
                "theme_status": cleared_status,
            },
        )
        return DeleteCollectionThemeResponse(
            status=Status.OK, has_theme=False, theme_status=cleared_status
        )

    async def _remove_server_theme(self, collection_id: int) -> None:
        """Delete the theme the server holds for a collection."""
        provider = self._access.provider()
        async with self._access.database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None or row.server_item_id is None:
            raise PublicServiceError(404, "Collection not found")
        if isinstance(provider.collections, UploadThemes):
            await provider.delete_collection_theme(row.server_item_id)
            return
        try:
            folder = await theme_folder(
                collection_id,
                app_config=self._app_config,
                database=self._access.database,
            )
        except DownloadError as exc:
            raise PublicServiceError(400, str(exc)) from exc
        await owned_thread(Path.unlink, folder / THEME_FILENAME, missing_ok=True)
        await provider.refresh_item(row.server_item_id, unlock=())
