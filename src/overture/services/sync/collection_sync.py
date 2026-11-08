"""Sync collections, their complete membership and their TMDB matches."""

lazy import logging
lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import dataclass
lazy from datetime import datetime

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import record_art_file
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import ThemeFileFacts, record_theme_file, theme_file_facts
lazy from ...domain import (
    ArtType,
    AssetScope,
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
lazy from ..downloads.service import DownloadService
lazy from ..public_dataset.downloads import queue_catalog_themes_for_collections

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _Placed:
    """A library a server collection holds members of."""

    library_id: str
    media_type: MediaType
    server_item_id: str


def _by_row(
    listed: Sequence[ServerCollection], rows: Sequence[MediaCollection]
) -> list[tuple[MediaCollection | None, list[ServerCollection]]]:
    """Group server collections by the row that owns them, lead copy first.

    Plex holds a cross-library collection as one collection in each library,
    so a row's copies are stored together; one unknown to Overture stands alone.
    """
    owners = {identity: row for row in rows for identity in row.server_ids}
    grouped: dict[int, tuple[MediaCollection, list[ServerCollection]]] = {}
    alone: list[tuple[MediaCollection | None, list[ServerCollection]]] = []
    for collection in listed:
        owner = owners.get(collection.id)
        if owner is None:
            alone.append((None, [collection]))
        else:
            grouped.setdefault(owner.id or 0, (owner, []))[1].append(collection)
    for row, copies in grouped.values():
        order = row.server_ids
        copies.sort(key=lambda copy: order.index(copy.id))
    return [*grouped.values(), *alone]


def _placement(
    copies: Sequence[ServerCollection],
    items: Mapping[str, ServerItemFacts],
    previous: MediaCollection | None,
) -> list[_Placed]:
    """The libraries these server collections hold members of.

    Plex names a collection's library; Jellyfin and Emby keep collections
    outside theirs, so its members say, and an emptied one stays where it was.
    """
    placed: dict[str, _Placed] = {}
    for copy in copies:
        if copy.library_id is not None and copy.media_type is not None:
            placed[copy.library_id] = _Placed(copy.library_id, copy.media_type, copy.id)
            continue
        for identity in copy.member_ids:
            if (item := items.get(identity)) is not None and item.library_id:
                placed.setdefault(
                    item.library_id,
                    _Placed(item.library_id, item.media_type, copy.id),
                )
    if placed or previous is None:
        return list(placed.values())
    return [
        _Placed(part.library_id, part.media_type, part.server_item_id)
        for part in previous.libraries
        if part.server_item_id is not None
    ]


def _store_placement(row: MediaCollection, placement: Sequence[_Placed]) -> None:
    """Make these the libraries of a collection Overture does not manage."""
    parts = {part.library_id: part for part in row.libraries}
    row.libraries = [
        parts.get(placed.library_id)
        or CollectionLibrary(
            collection_id=row.id or 0,
            library_id=placed.library_id,
            media_type=placed.media_type,
            server_item_id=placed.server_item_id,
        )
        for placed in placement
    ]
    for part, placed in zip(row.libraries, placement, strict=True):
        part.server_item_id = placed.server_item_id


class CollectionSync:
    """Mirror collections while preserving manual choices and inaccessible files."""

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        database: Database,
        downloads: DownloadService,
    ) -> None:
        self._registry = provider_registry
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
                rows = [
                    row
                    for row in await CollectionRepository(session).list_all()
                    if row.server_type is provider.server_type
                ]
                managed_ids = {
                    rule.collection_id
                    for rule in await CollectionRepository(session).rules()
                }
            seen = {collection.id for collection in listed}
            newly_identified: list[int] = []
            identified = 0
            for previous, copies in _by_row(listed, rows):
                if job.stop_requested():
                    return
                if previous is None and not import_unmanaged:
                    continue
                collection = copies[0]
                members = [
                    items[identity]
                    for copy in copies
                    for identity in copy.member_ids
                    if identity in items
                ]
                placement = _placement(copies, items, previous)
                # An empty BoxSet is in no library yet, so there is nothing to list.
                if not placement:
                    continue
                if library_ids and not {p.library_id for p in placement} & set(
                    library_ids
                ):
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
                            copies,
                            server_type=provider.server_type,
                            placement=placement,
                            members=members,
                            folder_themes=isinstance(
                                provider.collections, FolderThemes
                            ),
                            facts=facts,
                            theme_checked=checked,
                            managed=previous is not None and previous.id in managed_ids,
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
                gone = {
                    row.id: missing
                    for row in await CollectionRepository(session).list_all()
                    if row.id is not None
                    and row.server_type is provider.server_type
                    and (missing := set(row.server_ids) - seen)
                    and (
                        not library_ids
                        or (
                            row.last_synced_at is not None
                            and set(row.library_ids) & set(library_ids)
                        )
                    )
                }
                managed = await CollectionRepository(session).managed_ids(list(gone))
            for collection_id, missing in gone.items():
                async with (
                    self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
                    self._database.write_session() as session,
                ):
                    repo = CollectionRepository(session)
                    if collection_id in managed:
                        # Overture keeps what it manages; the next rule sync
                        # puts the collection back on the server.
                        await repo.clear_server_copies(
                            collection_id, utc_now(), missing
                        )
                        continue
                    await self._downloads.cancel_assets(
                        session, AssetScope(collection_id=collection_id)
                    )
                    await repo.delete_ids([collection_id])
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
                f"{len(gone) - len(managed)} removed, "
                f"{len(managed)} managed no longer on the server",
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
                    and (
                        not policy.library_ids
                        or set(row.library_ids) & set(policy.library_ids)
                    )
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
        copies: Sequence[ServerCollection],
        *,
        server_type: ServerType,
        placement: Sequence[_Placed],
        members: list[ServerItemFacts],
        folder_themes: bool,
        facts: ThemeFileFacts | None,
        theme_checked: bool,
        managed: bool,
        now: datetime,
    ) -> MediaCollection:
        """Store a collection from its server copies, the lead copy first."""
        collection = copies[0]
        row = await repository.find_server(
            server_type, collection.id
        ) or MediaCollection(
            server_type=server_type,
            created_at=now,
            tmdb_collection_id=collection.tmdb_id
            if any(placed.media_type is MediaType.MOVIE for placed in placement)
            else None,
        )
        for art_type, server_url in (
            (ArtType.POSTER, collection.thumb_url),
            (ArtType.BACKGROUND, collection.art_url),
        ):
            if row.id is not None and server_url != row.server_image_url(art_type):
                # The server shows another image than the one Overture uploaded.
                record_art_file(row, art_type, None)
        row.sqlmodel_update(
            {
                "kind": (
                    CollectionKind.SMART if collection.smart else CollectionKind.REGULAR
                ),
                "thumb_url": collection.thumb_url,
                "art_url": collection.art_url,
                "server_path": collection.path,
                "server_added_at": collection.added_at,
                "provider_tmdb_id": collection.tmdb_id,
                "last_synced_at": now,
                "updated_at": now,
            }
        )
        # What a managed collection spans is Overture's choice; otherwise it is
        # wherever the server's members are.
        if not managed:
            _store_placement(row, placement)
        # Overture owns what it manages, and its next sync sends those choices;
        # members saved in Overture and not yet synced win over the server's too.
        keep_members = row.id is not None and row.unsynced
        if not (keep_members or managed):
            _store_choices(row, collection)
        if not keep_members:
            row.child_count = sum(len(copy.member_ids) for copy in copies)
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
        if not keep_members:
            await repository.replace_members(row.id, [member.id for member in members])
        return row


def _store_choices(row: MediaCollection, collection: ServerCollection) -> None:
    """Take the title, summary, sorting and visibility the server holds."""
    if row.id is None or collection.summary != row.summary:
        row.summary_source = collection.summary
    if row.id is None or (
        row.summary is not None and row.summary_format == literal_template(row.summary)
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
            "title": collection.title,
            "summary": collection.summary,
            "sort_title": sort_title,
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
