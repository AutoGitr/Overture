"""Collection service operations."""

lazy import logging
lazy from datetime import timedelta
lazy from pathlib import Path

lazy from fastapi import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import read_art_slot
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import record_theme_file
lazy from ...domain import (
    ArtType,
    CollectionMatch,
    CollectionMode,
    CollectionOrder,
    CollectionPreset,
    ImageSize,
    MediaType,
    RuleSourceType,
    ServerType,
    SyncMode,
)
lazy from ...integrations.mdblist import MDBListClient
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...integrations.tmdb import TMDBClient
lazy from ...media_servers.adapters import UploadThemes
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.collections import (
    CollectionCreate,
    CollectionDetail,
    CollectionFilter,
    CollectionGenerateRequest,
    CollectionGenerateResponse,
    CollectionMatchRequest,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionPresetRead,
    CollectionRead,
    CollectionRuleRead,
    CollectionRuleWrite,
    CollectionSyncResponse,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
    collection_read,
    collection_theme_status_response,
)
lazy from ...schemas.common import (
    BulkMonitorResponse,
    EnqueuedJobResponse,
    MonitoredResponse,
    Status,
    StatusResponse,
)
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.security import sanitise_error
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..art.service import ArtService
lazy from ..downloads.collection_theme import (
    collection_theme_unavailable,
    collection_themes_unavailable,
    theme_folder,
)
lazy from ..downloads.queue import AssetScope, JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..library.items import media_item_reads_with_public_dataset_status
lazy from ..provider_images import proxy_provider_image
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from ..scheduler import SchedulerService
lazy from ..themes.youtube_resolver import DownloadError
lazy from . import COLLECTIONS_LOCK
lazy from .matching import apply_match

logger = logging.getLogger(__name__)


async def catalog_collections(
    session: AsyncSession, tmdb_ids: set[int], *, app_config: Settings
) -> dict[int, PublicDatasetCollection]:
    """Return the catalog's entries for these TMDB collections, if it is enabled."""
    schedule = await load_schedule(
        session, PUBLIC_DATASET_SCHEDULE, timezone=app_config.TZ
    )
    if not schedule.enabled or not tmdb_ids:
        return {}
    return await PublicDatasetRepository(session).collections_by_tmdb_id(tmdb_ids)


class CollectionsService:
    """Consolidated collections domain service."""

    def __init__(
        self,
        *,
        database: Database,
        provider_registry: ProviderRegistry,
        publisher: protocols.EventPublisher,
        downloads: DownloadService,
        proxy_clients: ProxyClientManager,
        app_config: Settings,
        tmdb: TMDBClient,
        mdblist: MDBListClient,
        scheduler: SchedulerService,
        art: ArtService,
    ) -> None:
        self._database = database
        self._provider_registry = provider_registry
        self._publisher = publisher
        self._downloads = downloads
        self._proxy_clients = proxy_clients
        self._app_config = app_config
        self._tmdb = tmdb
        self._mdblist = mdblist
        self._scheduler = scheduler
        self._art = art

    async def start(self) -> None:
        """Register a bounded poll; each rule owns its persisted due time."""
        self._scheduler.set_interval_job(
            "collection-rules", enabled=True, func=self.sync_due, minutes=1
        )

    async def stop(self) -> None:
        """Remove polling before the runtime closes its HTTP clients."""
        self._scheduler.remove_job("collection-rules")
        await self._mdblist.close()

    async def sync_due(self) -> None:
        """Run due rules independently so one failed source cannot stop others."""
        if self._provider_registry.collections is None:
            return
        async with self._database.read_session() as session:
            rules = await CollectionRepository(session).rules()
        now = utc_now()
        for rule in rules:
            if rule.last_synced_at and now < rule.last_synced_at + timedelta(
                hours=rule.sync_interval_hours
            ):
                continue
            async with self._database.read_session() as session:
                row = await CollectionRepository(session).get(rule.collection_id)
            if row is None or row.server_type is not self._provider().server_type:
                continue
            try:
                await self.sync_rule(rule.collection_id, row.media_type, scheduled=True)
            except Exception as exc:
                logger.warning(
                    "Collection rule %s failed: %s",
                    rule.collection_id,
                    sanitise_error(str(exc)),
                )

    @staticmethod
    def _rule_read(rule: CollectionRule | None) -> CollectionRuleRead | None:
        if rule is None:
            return None
        return CollectionRuleRead(
            **rule.model_dump(exclude={"id", "collection_id", "filter_json"}),
            filters=CollectionFilter.model_validate_json(rule.filter_json or "{}"),
        )

    @staticmethod
    def _sort_members(
        items: list[MediaItem], order: CollectionOrder
    ) -> list[MediaItem]:
        if order is CollectionOrder.CUSTOM:
            return items
        if order is CollectionOrder.ALPHA:
            return sorted(items, key=lambda item: (item.title.casefold(), item.id or 0))
        return sorted(
            items,
            key=lambda item: (item.year or 0, item.title.casefold(), item.id or 0),
        )

    @staticmethod
    def _filter_items(
        items: list[MediaItem], filters: CollectionFilter
    ) -> list[MediaItem]:
        return [
            item
            for item in items
            if (
                filters.decade is None
                or (item.year is not None and item.year // 10 * 10 == filters.decade)
            )
            and (
                filters.studio is None
                or (item.studio or "").casefold() == filters.studio.casefold()
            )
            and (
                filters.genre is None
                or filters.genre.casefold()
                in {genre.casefold() for genre in item.genres}
            )
        ]

    def _validate_options(
        self, options: CollectionOptions | CollectionMembersUpdate
    ) -> None:
        if self._provider().server_type is not ServerType.PLEX:
            if options.order_type is CollectionOrder.CUSTOM:
                raise PublicServiceError(
                    422, "Custom member order is only supported by Plex"
                )
            if isinstance(options, CollectionOptions) and (
                options.collection_mode not in {None, CollectionMode.DEFAULT}
                or options.visible_home
            ):
                raise PublicServiceError(
                    422,
                    "Visibility and home promotion require Plex",
                )

    async def _library_items(
        self, library_id: str, media_type: MediaType
    ) -> list[MediaItem]:
        sections = await self._provider().get_sections()
        if not any(
            section.key == library_id and section.media_type is media_type
            for section in sections
        ):
            raise PublicServiceError(
                422, "Select a library of the collection's media type"
            )
        async with self._database.read_session() as session:
            return await CollectionRepository(session).library_items(
                media_type, library_id
            )

    @staticmethod
    def _resolve_members(ids: list[int], items: list[MediaItem]) -> list[MediaItem]:
        by_id = {item.id: item for item in items}
        if len(set(ids)) != len(ids) or any(item_id not in by_id for item_id in ids):
            raise PublicServiceError(
                422,
                "Members must be distinct active server items in the selected library",
            )
        return [by_id[item_id] for item_id in ids]

    async def _push_options(
        self, row: MediaCollection, options: CollectionOptions
    ) -> None:
        async with self._database.read_session() as session:
            defaults = await get_app_settings(session)
        await self._provider().update_collection_details(
            row.server_item_id,
            title=options.title,
            summary=options.summary,
            sort_title=options.sort_title,
            mode=options.collection_mode or defaults.collection_mode_default,
            order=options.order_type,
            visible_home=options.visible_home,
        )

    async def create(self, body: CollectionCreate) -> CollectionDetail:
        """Create on the server, then record its complete local membership."""
        self._validate_options(body)
        items = self._sort_members(
            self._resolve_members(
                body.member_ids,
                await self._library_items(body.library_id, body.media_type),
            ),
            body.order_type,
        )
        async with self._database.read_session() as session:
            defaults = await get_app_settings(session)
        if len(items) < defaults.collection_minimum_items:
            raise PublicServiceError(
                422, "Collection has fewer members than the global minimum"
            )
        async with self._downloads.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._database.read_session() as session:
                existing = await CollectionRepository(session).list_listed(
                    body.media_type
                )
            if any(
                row.library_id == body.library_id
                and row.title.casefold() == body.title.casefold()
                and row.server_type is self._provider().server_type
                for row in existing
            ):
                raise PublicServiceError(
                    409, "A collection with this title already exists in this library"
                )
            server = await self._provider().create_collection(
                body.library_id,
                body.title,
                body.media_type,
                [item.server_item_id for item in items if item.server_item_id],
            )
            now = utc_now()
            row = MediaCollection(
                server_item_id=server.id,
                server_type=self._provider().server_type,
                media_type=body.media_type,
                library_id=body.library_id,
                child_count=len(items),
                server_link=server.server_link,
                server_path=server.path,
                last_synced_at=now,
                created_at=now,
                updated_at=now,
                **body.model_dump(exclude={"media_type", "library_id", "member_ids"}),
            )
            apply_match(row, [item.tmdb_collection_id for item in items])
            await self._push_options(row, body)
            if body.order_type is CollectionOrder.CUSTOM:
                await self._provider().set_collection_members(
                    row.server_item_id,
                    [item.server_item_id for item in items if item.server_item_id],
                    order=body.order_type,
                )
            async with self._database.write_session() as session:
                session.add(row)
                await session.flush()
                await CollectionRepository(session).replace_members(
                    row.id or 0, [item.id or 0 for item in items]
                )
        await self._publisher.broadcast("collections.changed")
        return await self.get_collection(row.id or 0, body.media_type)

    async def update(
        self, collection_id: int, media_type: MediaType, body: CollectionOptions
    ) -> CollectionDetail:
        """Edit collection metadata without touching movie or show metadata."""
        self._validate_options(body)
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
            await self._push_options(row, body)
            async with self._database.write_session() as session:
                row = await self._require(session, collection_id, media_type)
                row.sqlmodel_update(body.model_dump())
                row.updated_at = utc_now()
                session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, media_type)

    async def _delete_locked(self, row: MediaCollection) -> None:
        collection_id = row.id or 0
        await self._provider().delete_collection(row.server_item_id)
        async with self._database.write_session() as session:
            await self._downloads.cancel_assets(
                session, AssetScope(collection_id=collection_id)
            )
            await CollectionRepository(session).delete_ids([collection_id])
        await self._downloads.committed(session)
        await self._publisher.broadcast("collections.changed")

    async def delete(self, collection_id: int, media_type: MediaType) -> StatusResponse:
        """Delete a collection and cancel its assets, preserving all media."""
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
            await self._delete_locked(row)
        return StatusResponse(status=Status.DELETED)

    async def _set_members_locked(
        self,
        row: MediaCollection,
        items: list[MediaItem],
        order: CollectionOrder,
        *,
        append: bool = False,
    ) -> None:
        items = self._sort_members(items, order)
        server_ids = await self._provider().set_collection_members(
            row.server_item_id,
            [item.server_item_id for item in items if item.server_item_id],
            order=order,
            append=append,
        )
        async with self._database.read_session() as session:
            library_items = await CollectionRepository(session).library_items(
                row.media_type, row.library_id or ""
            )
        by_server_id = {item.server_item_id: item for item in library_items}
        stored_ids = [
            by_server_id[identity].id or 0
            for identity in server_ids
            if identity in by_server_id
        ]
        async with self._database.write_session() as session:
            current = await self._require(session, row.id or 0, row.media_type)
            await CollectionRepository(session).replace_members(row.id or 0, stored_ids)
            current.child_count = len(server_ids)
            current.order_type = order
            current.updated_at = utc_now()
            apply_match(
                current,
                [
                    by_server_id[identity].tmdb_collection_id
                    if identity in by_server_id
                    else None
                    for identity in server_ids
                ],
            )
            session.add(current)
        await self._publisher.broadcast("collection.updated", {"collection_id": row.id})

    async def set_members(
        self, collection_id: int, media_type: MediaType, body: CollectionMembersUpdate
    ) -> CollectionDetail:
        """Replace members, accepting custom order only on capable servers."""
        self._validate_options(body)
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
            items = self._resolve_members(
                body.member_ids,
                await self._library_items(row.library_id or "", media_type),
            )
            await self._push_options(
                row,
                CollectionOptions(
                    title=row.title,
                    summary=row.summary,
                    sort_title=row.sort_title,
                    collection_mode=row.collection_mode,
                    order_type=body.order_type,
                    visible_home=row.visible_home,
                ),
            )
            await self._set_members_locked(row, items, body.order_type)
        return await self.get_collection(collection_id, media_type)

    async def save_rule(
        self, collection_id: int, media_type: MediaType, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        """Persist validated rule settings; polling sees them after commit."""
        if body.source_type is RuleSourceType.TMDB:
            self._require_movie_matching(media_type)
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
                existing = await CollectionRepository(session).rule(collection_id)
            use_source_order = (
                existing is None
                and body.source_type is RuleSourceType.MDBLIST
                and row.server_type is ServerType.PLEX
            )
            if use_source_order:
                await self._push_options(
                    row,
                    CollectionOptions(
                        title=row.title,
                        summary=row.summary,
                        sort_title=row.sort_title,
                        collection_mode=row.collection_mode,
                        order_type=CollectionOrder.CUSTOM,
                        visible_home=row.visible_home,
                    ),
                )
            async with self._database.write_session() as session:
                await self._require(session, collection_id, media_type)
                rule = await CollectionRepository(session).rule(collection_id)
                fields = body.model_dump(exclude={"filters"})
                fields["filter_json"] = body.filters.model_dump_json()
                if rule is None:
                    rule = CollectionRule(collection_id=collection_id, **fields)
                else:
                    rule.sqlmodel_update(fields)
                rule.last_error = None
                rule.last_synced_at = None
                session.add(rule)
                if use_source_order:
                    row = await self._require(session, collection_id, media_type)
                    row.order_type = CollectionOrder.CUSTOM
                    session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        result = self._rule_read(rule)
        if result is None:
            raise RuntimeError("A saved rule must exist")
        return result

    async def delete_rule(
        self, collection_id: int, media_type: MediaType
    ) -> StatusResponse:
        """Stop automating membership without changing current members."""
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
            self._database.write_session() as session,
        ):
            await self._require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
            if rule is not None:
                await session.delete(rule)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return StatusResponse(status=Status.DELETED)

    async def _source_members(
        self, row: MediaCollection, rule: CollectionRule
    ) -> list[MediaItem]:
        async with self._database.read_session() as session:
            items = await CollectionRepository(session).library_items(
                row.media_type, row.library_id or ""
            )
        if rule.source_type is RuleSourceType.FILTER:
            return self._filter_items(
                items, CollectionFilter.model_validate_json(rule.filter_json or "{}")
            )
        if rule.source_type is RuleSourceType.MDBLIST:
            ids = await self._mdblist.tmdb_ids(rule.source_identifier, row.media_type)
        else:
            franchise = await self._tmdb.get_collection(int(rule.source_identifier))
            if franchise is None:
                raise PublicServiceError(
                    404, "TMDB collection not found; membership was kept"
                )
            ids = [
                part.tmdb_id
                for part in sorted(
                    franchise.parts,
                    key=lambda part: (part.release_date or "", part.tmdb_id),
                )
            ]
        rank = {tmdb_id: index for index, tmdb_id in enumerate(ids)}
        return sorted(
            [item for item in items if item.tmdb_id in rank],
            key=lambda item: (rank[item.tmdb_id or 0], item.id or 0),
        )

    async def sync_rule(
        self, collection_id: int, media_type: MediaType, *, scheduled: bool = False
    ) -> CollectionSyncResponse:
        """Resolve the whole source before changing any server membership."""
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
                rule = await CollectionRepository(session).rule(collection_id)
                defaults = await get_app_settings(session)
                current = await CollectionRepository(session).members(collection_id)
            if rule is None:
                raise PublicServiceError(404, "Collection has no dynamic rule")
            if scheduled and (
                not rule.enabled
                or (
                    rule.last_synced_at is not None
                    and utc_now()
                    < rule.last_synced_at + timedelta(hours=rule.sync_interval_hours)
                )
            ):
                return CollectionSyncResponse(skipped=True)
            error = None
            try:
                wanted = await self._source_members(row, rule)
                mode = rule.sync_mode or defaults.collection_sync_mode
                minimum = (
                    rule.minimum_items
                    if rule.minimum_items is not None
                    else defaults.collection_minimum_items
                )
                delete = (
                    rule.delete_below_minimum
                    if rule.delete_below_minimum is not None
                    else defaults.collection_delete_below_minimum
                )
                member_count = len(wanted)
                if mode is SyncMode.APPEND:
                    remote_ids = await self._provider().get_collection_member_ids(
                        row.server_item_id
                    )
                    member_count = len(
                        set(remote_ids) | {item.server_item_id for item in wanted}
                    )
                if member_count < minimum:
                    if delete:
                        await self._delete_locked(row)
                        return CollectionSyncResponse(
                            deleted=True, removed=len(current)
                        )
                    result = CollectionSyncResponse(skipped=True)
                else:
                    old, new = (
                        {item.id for item in current},
                        {item.id for item in wanted},
                    )
                    await self._push_options(
                        row,
                        CollectionOptions(
                            title=row.title,
                            summary=row.summary,
                            sort_title=row.sort_title,
                            collection_mode=row.collection_mode,
                            order_type=row.order_type,
                            visible_home=row.visible_home,
                        ),
                    )
                    await self._set_members_locked(
                        row, wanted, row.order_type, append=mode is SyncMode.APPEND
                    )
                    result = CollectionSyncResponse(
                        added=len(new - old),
                        removed=len(old - new) if mode is SyncMode.SYNC else 0,
                    )
                error = None
            except Exception as exc:
                error = sanitise_error(str(exc))
                raise
            finally:
                async with self._database.write_session() as session:
                    saved = await CollectionRepository(session).rule(collection_id)
                    if saved is not None:
                        saved.last_synced_at = utc_now()
                        saved.last_error = error
                        session.add(saved)
                await self._publisher.broadcast(
                    "collection.updated", {"collection_id": collection_id}
                )
        if not result.skipped:
            try:
                await self._auto_assets(collection_id, media_type)
            except Exception as exc:
                message = "Members synced; automatic assets failed: " + sanitise_error(
                    str(exc)
                )
                async with self._database.write_session() as session:
                    saved = await CollectionRepository(session).rule(collection_id)
                    if saved is not None:
                        saved.last_error = message
                        session.add(saved)
                await self._publisher.broadcast(
                    "collection.updated", {"collection_id": collection_id}
                )
                raise PublicServiceError(502, message) from exc
        return result

    async def _auto_assets(self, collection_id: int, media_type: MediaType) -> None:
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            defaults = await get_app_settings(session)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
                app_config=self._app_config,
            )
        if defaults.collection_auto_match_art:
            for art_type in (ArtType.POSTER, ArtType.BACKGROUND):
                if read_art_slot(row, art_type).url:
                    continue
                sources = await self._art.get_collection_sources(
                    collection_id, media_type, art_type
                )
                candidates = [
                    candidate
                    for group in sources.sources.values()
                    for candidate in group
                ]
                if candidates:
                    await self._art.save_collection(
                        collection_id,
                        media_type,
                        art_type,
                        SaveArtRequest(url=candidates[0].url),
                    )
        entry = catalog.get(row.tmdb_collection_id or 0)
        if (
            defaults.collection_auto_match_theme
            and not row.youtube_id
            and entry
            and entry.youtube_id_overturedb
            and collection_themes_unavailable(self._provider(), self._app_config)
            is None
        ):
            await self.set_collection_theme(
                collection_id,
                SetCollectionThemeRequest(
                    media_type=media_type, youtube_id=entry.youtube_id_overturedb
                ),
            )

    async def presets(
        self, body: CollectionGenerateRequest
    ) -> list[CollectionPresetRead]:
        """Preview reusable filters, excluding undersized or existing collections."""
        items = await self._library_items(body.library_id, body.media_type)
        async with self._database.read_session() as session:
            defaults = await get_app_settings(session)
            existing = await CollectionRepository(session).list_listed(body.media_type)
        used = {
            row.title.casefold()
            for row in existing
            if row.library_id == body.library_id
            and row.server_type is self._provider().server_type
        }
        if body.preset is CollectionPreset.TMDB_COLLECTIONS:
            self._require_movie_matching(body.media_type)
            used_ids = {
                row.tmdb_collection_id
                for row in existing
                if row.library_id == body.library_id
                and row.server_type is self._provider().server_type
            }
            counts: dict[int, int] = {}
            for item in items:
                if item.tmdb_collection_id is not None:
                    identity = item.tmdb_collection_id
                    counts[identity] = counts.get(identity, 0) + 1
            previews: list[CollectionPresetRead] = []
            for identity, count in sorted(counts.items()):
                if identity in used_ids or count < defaults.collection_minimum_items:
                    continue
                franchise = await self._tmdb.get_collection(identity)
                if franchise is not None and franchise.title.casefold() not in used:
                    previews.append(
                        CollectionPresetRead(
                            title=franchise.title,
                            count=count,
                            filters=CollectionFilter(),
                            tmdb_collection_id=identity,
                        )
                    )
            return sorted(previews, key=lambda preview: preview.title)
        filters: dict[str, CollectionFilter] = {}
        for item in items:
            if body.preset is CollectionPreset.DECADES and item.year:
                decade = item.year // 10 * 10
                filters[f"{decade}s"] = CollectionFilter(decade=decade)
            elif body.preset is CollectionPreset.STUDIOS and item.studio:
                filters[item.studio] = CollectionFilter(studio=item.studio)
            elif body.preset is CollectionPreset.GENRES:
                filters.update(
                    {genre: CollectionFilter(genre=genre) for genre in item.genres}
                )
        return [
            CollectionPresetRead(
                title=title,
                count=len(self._filter_items(items, filters[title])),
                filters=filters[title],
            )
            for title in sorted(filters)
            if title.casefold() not in used
            and len(self._filter_items(items, filters[title]))
            >= defaults.collection_minimum_items
        ]

    async def generate(
        self, body: CollectionGenerateRequest
    ) -> CollectionGenerateResponse:
        """Create selected previews independently and attach their filter rules."""
        previews = {preset.title: preset for preset in await self.presets(body)}
        if (
            not body.titles
            or len(set(body.titles)) != len(body.titles)
            or any(title not in previews for title in body.titles)
        ):
            raise PublicServiceError(
                422, "Select distinct collections from the current preview"
            )
        items = await self._library_items(body.library_id, body.media_type)
        response = CollectionGenerateResponse()
        for title in body.titles:
            preset = previews[title]
            filters = preset.filters
            tmdb_id = preset.tmdb_collection_id
            try:
                detail = await self.create(
                    CollectionCreate(
                        title=title,
                        collection_group=body.preset.collection_group,
                        library_id=body.library_id,
                        media_type=body.media_type,
                        member_ids=[
                            item.id or 0
                            for item in (
                                [
                                    item
                                    for item in items
                                    if item.tmdb_collection_id == tmdb_id
                                ]
                                if tmdb_id is not None
                                else self._filter_items(items, filters)
                            )
                        ],
                    )
                )
                response.created.append(detail.id)
                await self.save_rule(
                    detail.id,
                    body.media_type,
                    CollectionRuleWrite(
                        source_type=RuleSourceType.TMDB
                        if tmdb_id is not None
                        else RuleSourceType.FILTER,
                        source_identifier=str(tmdb_id) if tmdb_id is not None else "",
                        filters=filters,
                    ),
                )
            except Exception as exc:
                response.errors[title] = sanitise_error(str(exc))
        return response

    def _provider(self) -> CollectionProvider:
        """Return the media server's provider when it supports collections.

        Raises:
            PublicServiceError: When the media server has no collections.
        """
        provider = self._provider_registry.collections
        if provider is None:
            raise PublicServiceError(
                400, "The media server does not support collections."
            )
        return provider

    async def _require(
        self, session: AsyncSession, collection_id: int, media_type: MediaType
    ) -> MediaCollection:
        """Return a listed collection of the requested media type.

        Raises:
            PublicServiceError: When the last sync listed no such collection.
        """
        provider = self._provider()
        row = await CollectionRepository(session).get_listed(collection_id, media_type)
        if row is None or row.server_type is not provider.server_type:
            raise PublicServiceError(
                404, "Collection not found for the selected media type"
            )
        return row

    async def list_collections(self, media_type: MediaType) -> list[CollectionRead]:
        """Return the collections the last sync listed for the media type."""
        self._provider()
        async with self._database.read_session() as session:
            rows = await CollectionRepository(session).list_listed(media_type)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id for row in rows if row.tmdb_collection_id},
                app_config=self._app_config,
            )
        return [
            collection_read(row, catalog.get(row.tmdb_collection_id or 0))
            for row in rows
        ]

    async def groups(self, media_type: MediaType) -> list[str]:
        """Return preset groups and custom groups used on the active server."""
        provider = self._provider()
        async with self._database.read_session() as session:
            rows = await CollectionRepository(session).list_listed(media_type)
        return sorted(
            {preset.collection_group for preset in CollectionPreset}
            | {
                row.collection_group
                for row in rows
                if row.server_type is provider.server_type and row.collection_group
            }
        )

    async def get_collection(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionDetail:
        """Return one collection with its members and catalog entry."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            members = self._sort_members(
                await CollectionRepository(session).members(row.id or 0), row.order_type
            )
            rule = self._rule_read(
                await CollectionRepository(session).rule(collection_id)
            )
            member_reads = await media_item_reads_with_public_dataset_status(
                session, members
            )
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
                app_config=self._app_config,
            )
        entry = catalog.get(row.tmdb_collection_id or 0)
        reason = await collection_theme_unavailable(
            row, provider=self._provider(), app_config=self._app_config
        )
        return CollectionDetail(
            **collection_read(row, entry).model_dump(),
            tmdb_match_confidence=(
                sum(
                    item.tmdb_collection_id == row.tmdb_collection_id
                    for item in members
                )
                / max(row.child_count, len(members))
                if row.tmdb_collection_id is not None and (row.child_count or members)
                else None
            ),
            theme_duration=row.theme_file_duration or row.youtube_duration,
            members=member_reads,
            rule=rule,
            theme_unavailable=reason,
            theme_writable=reason is None,
            catalog_entry_key=f"tmdb-{entry.tmdb_id}" if entry else None,
            catalog_title=entry.title if entry else None,
            youtube_id_overturedb=entry.youtube_id_overturedb if entry else None,
            youtube_id_themerrdb=entry.youtube_id_themerrdb if entry else None,
        )

    async def get_collection_theme(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionThemeStatusResponse:
        """Return the current theme status for a collection."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
        return collection_theme_status_response(collection_read(row, None))

    async def set_collection_theme(
        self, collection_id: int, body: SetCollectionThemeRequest
    ) -> EnqueuedJobResponse:
        """Queue a YouTube track to become the theme of a collection."""
        reason = collection_themes_unavailable(self._provider(), self._app_config)
        if reason is not None:
            raise PublicServiceError(400, reason)
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, body.media_type)
        target = JobTarget.collection_theme(collection_id, row.title, body.youtube_id)
        async with self._downloads.asset_locks.acquire(target.slot.lock_key):
            reason = await collection_theme_unavailable(
                row, provider=self._provider(), app_config=self._app_config
            )
            if reason:
                raise PublicServiceError(400, reason)
            async with self._database.write_session() as session:
                await self._require(session, collection_id, body.media_type)
                job_id, _ = await self._downloads.queue_job(session, target)
        await self._downloads.committed(session)
        return EnqueuedJobResponse(job_id=job_id)

    async def _remove_server_theme(self, collection_id: int) -> None:
        """Delete the theme the server holds for a collection."""
        provider = self._provider()
        async with self._database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None:
            raise PublicServiceError(404, "Collection not found")
        if isinstance(provider.collections, UploadThemes):
            await provider.delete_collection_theme(row.server_item_id)
            return
        try:
            folder = await theme_folder(
                collection_id, app_config=self._app_config, database=self._database
            )
        except DownloadError as exc:
            raise PublicServiceError(400, str(exc)) from exc
        await owned_thread(Path.unlink, folder / THEME_FILENAME, missing_ok=True)
        await provider.refresh_item(row.server_item_id, unlock=())

    async def delete_collection_theme(
        self, collection_id: int, media_type: MediaType
    ) -> DeleteCollectionThemeResponse:
        """Remove the theme from a collection and clear its stored record."""
        async with self._database.read_session() as session:
            await self._require(session, collection_id, media_type)
        scope = AssetScope(collection_id=collection_id)
        async with self._downloads.asset_locks.acquire(scope.lock_key):
            await self._remove_server_theme(collection_id)
            async with self._database.write_session() as db:
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
        await self._publisher.broadcast(
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

    async def set_collection_monitored(
        self, collection_id: int, media_type: MediaType, monitored: bool
    ) -> MonitoredResponse:
        """Set whether a collection is monitored."""
        async with self._database.write_session() as session:
            row = await self._require(session, collection_id, media_type)
            row.monitored = monitored
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return MonitoredResponse(monitored=monitored)

    async def bulk_set_collection_monitored(
        self, collection_ids: list[int], media_type: MediaType, monitored: bool
    ) -> BulkMonitorResponse:
        """Set the monitored flag for multiple collections at once."""
        self._provider()
        async with self._database.write_session() as db:
            updated = await CollectionRepository(db).bulk_set_monitored(
                collection_ids, media_type, monitored, timestamp=utc_now()
            )
        await self._publisher.broadcast("collections.changed")
        return BulkMonitorResponse(updated=updated)

    async def set_match(
        self, collection_id: int, body: CollectionMatchRequest
    ) -> CollectionDetail:
        """Match a collection to a TMDB collection, or keep it unmatched."""
        self._require_movie_matching(body.media_type)
        async with self._database.write_session() as session:
            row = await self._require(session, collection_id, body.media_type)
            row.tmdb_collection_id = body.tmdb_collection_id
            row.tmdb_match = (
                CollectionMatch.MANUAL
                if body.tmdb_collection_id is not None
                else CollectionMatch.UNMATCHED
            )
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, body.media_type)

    async def reset_match(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionDetail:
        """Let the server's ID and the members decide the match again."""
        self._require_movie_matching(media_type)
        async with self._database.write_session() as session:
            row = await self._require(session, collection_id, media_type)
            row.tmdb_match = CollectionMatch.AUTO
            member_ids = await CollectionRepository(session).member_ids(row.id or 0)
            facts = await MediaItemRepository(session).tmdb_collection_ids(member_ids)
            facts.extend([None] * max(0, row.child_count - len(facts)))
            row.tmdb_collection_id = None
            apply_match(row, facts)
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, media_type)

    @staticmethod
    def _require_movie_matching(media_type: MediaType) -> None:
        if media_type is not MediaType.MOVIE:
            raise PublicServiceError(422, "TMDB matching is only available for movies")

    async def proxy_collection_image(
        self, collection_id: int, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy a collection's poster or background with bounded response size."""
        provider = self._provider()
        if art_type.owned_by_season:
            raise PublicServiceError(404, "Collection image not found")
        async with self._database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None or row.last_synced_at is None:
            raise PublicServiceError(404, "Collection not found")
        request = await provider.build_collection_image_request(
            row.server_item_id, art_type, size
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
