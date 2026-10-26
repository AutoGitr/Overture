"""Sync collections, their complete membership and their TMDB matches."""

lazy import logging
lazy from collections import Counter
lazy from collections.abc import Sequence
lazy from datetime import datetime

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import ThemeFileFacts, record_theme_file, theme_file_facts
lazy from ...domain import (
    CollectionKind,
    CollectionOrder,
    IncrementalThemeOrder,
    MediaType,
    ScheduleKind,
    ServerType,
)
lazy from ...jobs.progress_log import JobOutcome, log_entry
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import SyncTally
lazy from ...media_servers.adapters import FolderThemes, ServerCollection
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.media_items import MediaItemRepository, ServerItemFacts
lazy from ...repositories.saved_schedules import SavedScheduleRepository
lazy from ...schemas.sync import SyncScheduleConfig
lazy from ...utils.collection_formats import literal_template
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections import COLLECTIONS_LOCK
lazy from ..collections.theme_files import collection_folder, inspect_theme_file
lazy from ..downloads.queue import AssetScope
lazy from ..downloads.service import DownloadService
lazy from ..public_dataset.downloads import queue_catalog_themes_for_collections
lazy from .tmdb_collections import TmdbCollectionEnrichment

logger = logging.getLogger(__name__)


def _most_common[T](values: Sequence[T]) -> T | None:
    return Counter(values).most_common(1)[0][0] if values else None


class CollectionSync:
    """Mirror collections while preserving manual choices and inaccessible files."""

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        enrichment: TmdbCollectionEnrichment,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        database: Database,
        downloads: DownloadService,
    ) -> None:
        self._registry = provider_registry
        self._enrichment = enrichment
        self._publisher = publisher
        self._config = app_config
        self._database = database
        self._downloads = downloads

    async def run(
        self,
        job: ManagedJob[SyncTally],
        *,
        library_ids: list[str] | None,
        theme_order: IncrementalThemeOrder = IncrementalThemeOrder.OFF,
    ) -> None:
        """Refresh collections, then queue catalog themes for new matches."""
        if job.stop_requested():
            return
        await self._enrichment.run(job, library_ids=library_ids)
        provider = self._registry.collections
        if provider is None or job.stop_requested():
            return
        await job.progress(
            log=log_entry(
                JobOutcome.STARTED, "Collections", "reading server collections"
            )
        )
        async with self._downloads.asset_locks.acquire(COLLECTIONS_LOCK):
            listed = await provider.list_collections()
            async with self._database.read_session() as session:
                import_unmanaged = (
                    await get_app_settings(session)
                ).collection_import_unmanaged
                items = await MediaItemRepository(session).facts_by_server_id()
                existing = {
                    row.server_item_id: row
                    for row in await CollectionRepository(session).list_all()
                    if row.server_type is provider.server_type
                }
            seen = {collection.id for collection in listed}
            newly_identified: list[int] = []
            identified = 0
            for collection in listed:
                if job.stop_requested():
                    return
                previous = existing.get(collection.id)
                if previous is None and not import_unmanaged:
                    continue
                members = [items[i] for i in collection.member_ids if i in items]
                media_type = (
                    collection.media_type
                    or _most_common([m.media_type for m in members])
                    or (previous.media_type if previous else MediaType.MOVIE)
                )
                library_id = (
                    collection.library_id
                    or _most_common([m.library_id for m in members])
                    or (previous.library_id if previous else None)
                )
                if library_ids and library_id not in library_ids:
                    continue
                async with self._downloads.asset_locks.acquire(
                    f"collection:{previous.id}"
                    if previous
                    else f"new-collection:{provider.server_type}:{collection.id}"
                ):
                    async with self._database.read_session() as session:
                        current = await CollectionRepository(session).find_server(
                            provider.server_type, collection.id
                        )
                    facts, checked = await self._inspect_theme(
                        provider, collection, current, previous
                    )
                    async with self._database.write_session() as session:
                        row = await self._store(
                            CollectionRepository(session),
                            collection,
                            server_type=provider.server_type,
                            media_type=media_type,
                            library_id=library_id,
                            members=members,
                            folder_themes=isinstance(
                                provider.collections, FolderThemes
                            ),
                            facts=facts,
                            theme_checked=checked,
                            now=utc_now(),
                        )
                identified += row.tmdb_collection_id is not None
                if (
                    row.id is not None
                    and row.tmdb_collection_id is not None
                    and (
                        previous is None
                        or previous.tmdb_collection_id != row.tmdb_collection_id
                    )
                ):
                    newly_identified.append(row.id)
                await self._publisher.broadcast(
                    "collection.updated", {"collection_id": row.id}
                )
            async with self._database.read_session() as session:
                gone = [
                    row.id
                    for row in await CollectionRepository(session).list_all()
                    if row.id is not None
                    and row.server_type is provider.server_type
                    and row.server_item_id is not None
                    and row.server_item_id not in seen
                    and (
                        not library_ids
                        or (
                            row.last_synced_at is not None
                            and row.library_id in library_ids
                        )
                    )
                ]
            for collection_id in gone:
                async with (
                    self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
                    self._database.write_session() as session,
                ):
                    await self._downloads.cancel_assets(
                        session, AssetScope(collection_id=collection_id)
                    )
                    await CollectionRepository(session).delete_ids([collection_id])
                await self._downloads.committed(session)
            await self._publisher.broadcast("collections.changed")
        await queue_catalog_themes_for_collections(
            newly_identified,
            theme_order=theme_order,
            downloads=self._downloads,
            app_config=self._config,
            database=self._database,
        )
        if theme_order is IncrementalThemeOrder.OFF and newly_identified:
            await self._queue_incremental_choices(newly_identified)
        await job.progress(
            log=log_entry(
                JobOutcome.STARTED,
                "Collections",
                f"{len(listed)} listed, {identified} with TMDB IDs, "
                f"{len(gone)} removed",
            )
        )

    async def _inspect_theme(
        self,
        provider: CollectionProvider,
        collection: ServerCollection,
        current: MediaCollection | None,
        previous: MediaCollection | None,
    ) -> tuple[ThemeFileFacts | None, bool]:
        """Keep provenance when the mount is unavailable or a newer upload won."""
        if not isinstance(provider.collections, FolderThemes):
            changed = bool(
                current
                and previous
                and current.server_theme_id != previous.server_theme_id
            )
            return None, not changed
        if self._config.JELLYFIN_COLLECTIONS_PATH and collection.path:
            try:
                folder = await owned_thread(
                    collection_folder,
                    self._config.JELLYFIN_COLLECTIONS_PATH,
                    collection.path,
                )
                facts = await owned_thread(
                    inspect_theme_file,
                    folder,
                    theme_file_facts(current) if current else None,
                )
                return facts, True
            except OSError, ValueError:
                logger.debug(
                    "Collection theme folder unavailable: %s", collection.title
                )
        return None, False

    async def _queue_incremental_choices(self, collection_ids: list[int]) -> None:
        """Use the oldest enabled incremental policy covering each collection."""
        async with self._database.read_session() as session:
            schedules = await SavedScheduleRepository(session).of_kind(
                ScheduleKind.SYNC
            )
            policies = [
                SyncScheduleConfig.model_validate(row.payload)
                for row in schedules
                if row.enabled
            ]
            rows = await CollectionRepository(session).bulk_targets(
                collection_ids=collection_ids
            )
        groups: dict[IncrementalThemeOrder, list[int]] = {}
        for row in rows:
            for policy in policies:
                if (
                    policy.mode == "incremental"
                    and policy.download_themes is not IncrementalThemeOrder.OFF
                    and (not policy.library_ids or row.library_id in policy.library_ids)
                ):
                    groups.setdefault(policy.download_themes, []).append(row.id or 0)
                    break
        for order, ids in groups.items():
            await queue_catalog_themes_for_collections(
                ids,
                theme_order=order,
                downloads=self._downloads,
                app_config=self._config,
                database=self._database,
            )

    @staticmethod
    async def _store(
        repository: CollectionRepository,
        collection: ServerCollection,
        *,
        server_type: ServerType,
        media_type: MediaType,
        library_id: str | None,
        members: list[ServerItemFacts],
        folder_themes: bool,
        facts: ThemeFileFacts | None,
        theme_checked: bool,
        now: datetime,
    ) -> MediaCollection:
        row = await repository.find_server(
            server_type, collection.id
        ) or MediaCollection(
            server_item_id=collection.id,
            media_type=media_type,
            server_type=server_type,
            created_at=now,
            tmdb_collection_id=collection.tmdb_id
            if media_type is MediaType.MOVIE
            else None,
        )
        if row.id is None or collection.summary != row.summary:
            row.summary_source = collection.summary
        if row.id is None or (
            row.summary is not None
            and row.summary_format == literal_template(row.summary)
        ):
            row.summary_format = (
                literal_template(collection.summary)
                if collection.summary is not None
                else None
            )
        sort_title = collection.sort_title or row.sort_title
        if row.id is None or (
            row.sort_title is not None
            and row.sort_title_format == literal_template(row.sort_title)
        ):
            row.sort_title_format = (
                literal_template(sort_title) if sort_title is not None else None
            )
        row.sqlmodel_update(
            {
                "media_type": media_type,
                "kind": (
                    CollectionKind.SMART if collection.smart else CollectionKind.REGULAR
                ),
                "title": collection.title,
                "summary": collection.summary,
                "sort_title": sort_title,
                "library_id": library_id,
                "child_count": len(collection.member_ids),
                "thumb_url": collection.thumb_url,
                "art_url": collection.art_url,
                "server_link": collection.server_link,
                "server_path": collection.path,
                "server_added_at": collection.added_at,
                "provider_tmdb_id": collection.tmdb_id,
                "last_synced_at": now,
                "updated_at": now,
            }
        )
        if collection.collection_mode is not None:
            row.collection_mode = collection.collection_mode
        if collection.collection_filtering is not None:
            row.collection_filtering = collection.collection_filtering
        # Overture keeps orders the server cannot sort by as a custom order.
        computed = row.order_type not in {
            CollectionOrder.RELEASE_ASC,
            CollectionOrder.TITLE_ASC,
        }
        if collection.order_type is not None and not (
            collection.order_type is CollectionOrder.CUSTOM and computed
        ):
            row.order_type = collection.order_type
        if theme_checked:
            replaced = (
                (
                    row.theme_file_hash is not None
                    and facts is not None
                    and row.theme_file_hash != facts.file_hash
                )
                if folder_themes
                else row.server_theme_id != collection.theme_id
            )
            if replaced:
                row.sqlmodel_update(
                    {
                        "youtube_id": None,
                        "youtube_id_source": None,
                        "youtube_title": None,
                        "youtube_duration": None,
                    }
                )
            if folder_themes:
                record_theme_file(row, facts)
                row.server_theme_id = None
            else:
                row.server_theme_id = collection.theme_id
        repository.session.add(row)
        await repository.session.flush()
        if row.id is None:
            raise RuntimeError("Collection row was not assigned an ID")
        await repository.replace_members(row.id, [member.id for member in members])
        return row
