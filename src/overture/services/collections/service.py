"""Collection service operations."""

lazy import logging
lazy from dataclasses import dataclass, field
lazy from datetime import datetime, timedelta
lazy from pathlib import Path
lazy from typing import Any

lazy from fastapi import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import read_art_slot
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import record_theme_file
lazy from ...domain import (
    ArtType,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    ImageSize,
    MediaType,
    ServerType,
    SyncMode,
)
lazy from ...integrations.arr import ArrClient
lazy from ...integrations.mdblist import MDBListClient
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...integrations.tmdb import TMDBClient
lazy from ...jobs.gate import LibraryGate
lazy from ...media_servers.adapters import ServerCollection, UploadThemes
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.collections import (
    ArrTagRead,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionBuilder,
    CollectionCreate,
    CollectionDetail,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionPolicyBase,
    CollectionPresetCreate,
    CollectionPresetEntry,
    CollectionPresetPreview,
    CollectionPresetResult,
    CollectionRead,
    CollectionRuleRead,
    CollectionRuleWrite,
    CollectionSyncResponse,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    DynamicTmdbGroupConfig,
    LibraryFilterBuilder,
    MdblistBuilder,
    RadarrTagBuilder,
    SetCollectionThemeRequest,
    SmartCollectionConfig,
    SonarrTagBuilder,
    TmdbCollectionBuilder,
    TmdbItemBuilder,
    TmdbListBuilder,
    TmdbPersonBuilder,
    builders_adapter,
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
lazy from ...utils.collection_formats import (
    format_sort_title,
    format_summary,
    is_within_active_window,
    literal_template,
    strip_affixes,
)
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
lazy from .filters import compile_plex_smart_filter, evaluate_filter_group
lazy from .policy import CollectionPolicy, RuleOrPolicy, resolve_policy
lazy from .presets import preview_preset

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


@dataclass(slots=True)
class GroupSyncResult:
    """Outcomes from syncing one collection group."""

    created: list[int] = field(default_factory=list[int])
    errors: dict[str, str] = field(default_factory=dict[str, str])


_DISPLAY_OVERRIDES = frozenset(
    {
        "collection_mode",
        "order_type",
        "collection_filtering",
        "visible_home",
        "visible_shared",
        "visible_library",
    }
)


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
        radarr: ArrClient | None = None,
        sonarr: ArrClient | None = None,
        library_gate: LibraryGate | None = None,
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
        self._radarr = radarr or ArrClient(
            kind="radarr",
            base_url=app_config.RADARR_URL,
            api_key=app_config.RADARR_API_KEY.get_secret_value(),
            verify_tls=app_config.RADARR_VERIFY_TLS,
        )
        self._sonarr = sonarr or ArrClient(
            kind="sonarr",
            base_url=app_config.SONARR_URL,
            api_key=app_config.SONARR_API_KEY.get_secret_value(),
            verify_tls=app_config.SONARR_VERIFY_TLS,
        )
        self._library_gate = library_gate

    async def start(self) -> None:
        """Register a bounded poll; each rule owns its persisted due time."""
        self._scheduler.set_interval_job(
            "collection-rules", enabled=True, func=self.sync_due, minutes=1
        )

    async def stop(self) -> None:
        """Remove polling before the runtime closes its HTTP clients."""
        self._scheduler.remove_job("collection-rules")
        await self._mdblist.close()
        await self._radarr.close()
        await self._sonarr.close()

    async def list_radarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Radarr."""
        return [
            ArrTagRead(id=tag.id, label=tag.label)
            for tag in await self._radarr.list_tags()
        ]

    async def list_sonarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Sonarr."""
        return [
            ArrTagRead(id=tag.id, label=tag.label)
            for tag in await self._sonarr.list_tags()
        ]

    async def sync_due(self) -> None:
        """Run due rules independently so one failed source cannot stop others."""
        if self._provider_registry.collections is None:
            return
        if (
            self._library_gate is not None
            and self._library_gate.blocker("downloads") is not None
        ):
            return
        async with self._database.read_session() as session:
            rules = await CollectionRepository(session).rules(enabled_only=False)
            groups = await CollectionRepository(session).group_policies(
                self._provider().server_type, MediaType.MOVIE
            )
        for group in groups:
            if group.dynamic_tmdb_json:
                try:
                    config = DynamicTmdbGroupConfig.model_validate_json(
                        group.dynamic_tmdb_json
                    )
                    if config.enabled:
                        await self._sync_dynamic_tmdb_group(group, config)
                except Exception as exc:
                    logger.warning(
                        "Dynamic TMDB group %s failed: %s",
                        group.name,
                        sanitise_error(str(exc)),
                    )
        now = utc_now()
        for rule in rules:
            async with self._database.read_session() as session:
                row = await CollectionRepository(session).get(rule.collection_id)
                if row is None or row.server_type is not self._provider().server_type:
                    continue
                policy = await self._policy(
                    session, row.media_type, row.collection_group, rule
                )
            if not policy.sync_enabled or policy.sync_interval_hours <= 0:
                continue
            if rule.last_synced_at and now < rule.last_synced_at + timedelta(
                hours=policy.sync_interval_hours
            ):
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
    def _rule_builders(rule: CollectionRule) -> list[CollectionBuilder]:
        if rule.builders_json:
            return builders_adapter.validate_json(rule.builders_json)
        return []

    @staticmethod
    def _rule_smart_filter(rule: CollectionRule) -> SmartCollectionConfig | None:
        if not rule.smart_filter_json:
            return None
        return SmartCollectionConfig.model_validate_json(rule.smart_filter_json)

    @classmethod
    def _rule_read(cls, rule: CollectionRule | None) -> CollectionRuleRead | None:
        if rule is None:
            return None
        return CollectionRuleRead(
            **rule.model_dump(
                exclude={
                    "id",
                    "collection_id",
                    "filter_json",
                    "builders_json",
                    "smart_filter_json",
                    "source_type",
                    "source_identifier",
                }
            ),
            builders=cls._rule_builders(rule),
            smart_filter=cls._rule_smart_filter(rule),
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

    def _validate_options(
        self, options: CollectionOptions | CollectionMembersUpdate
    ) -> None:
        if self._provider().server_type is not ServerType.PLEX:
            if options.order_type is CollectionOrder.CUSTOM:
                raise PublicServiceError(
                    422, "Custom member order is only supported by Plex"
                )
            if isinstance(options, CollectionOptions):
                if options.kind is CollectionKind.SMART:
                    raise PublicServiceError(
                        422, "Smart collections are only supported by Plex"
                    )
                if (
                    options.collection_mode not in {None, CollectionMode.DEFAULT}
                    or options.visible_home
                    or options.visible_shared
                    or options.visible_library
                    or options.collection_filtering is not None
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
        self,
        row: MediaCollection,
        options: CollectionOptions,
        rule: RuleOrPolicy = None,
    ) -> CollectionOptions:
        async with self._database.read_session() as session:
            if rule is None and row.id is not None:
                rule = await CollectionRepository(session).rule(row.id)
            policy = await self._policy(
                session, row.media_type, options.collection_group, rule
            )
        sort_title = self._inherited_sort_title(options, policy)
        template = (
            options.summary_format
            if options.summary_format is not None
            else policy.summary_format
        )
        summary_options = options
        if options.summary is None and (not template or "{summary}" in template):
            summary_options = options.model_copy(update={"summary": row.summary_source})
        summary = self._inherited_summary(summary_options, policy)
        order = (
            options.order_type
            if "order_type" in options.model_fields_set
            else policy.order_type
        )
        visible_home = (
            options.visible_home
            if "visible_home" in options.model_fields_set
            else policy.visible_home
        )
        visible_shared = (
            options.visible_shared
            if "visible_shared" in options.model_fields_set
            else policy.visible_shared
        )
        visible_library = (
            options.visible_library
            if "visible_library" in options.model_fields_set
            else policy.visible_library
        )
        filtering = options.collection_filtering or (
            policy.collection_filtering
            if options.kind is CollectionKind.SMART
            or policy.collection_filtering is not CollectionFiltering.ADMIN
            else None
        )
        effective = options.model_copy(
            update={
                "sort_title": sort_title,
                "summary": summary,
                "order_type": order,
                "visible_home": visible_home,
                "visible_shared": visible_shared,
                "visible_library": visible_library,
                "collection_mode": options.collection_mode or policy.collection_mode,
                "collection_filtering": filtering,
            }
        )
        if row.server_item_id is None:
            return effective
        await self._provider().update_collection_details(
            row.server_item_id,
            title=options.title,
            summary=summary,
            sort_title=sort_title,
            mode=options.collection_mode or policy.collection_mode,
            order=order,
            visible_home=visible_home,
            visible_shared=visible_shared,
            visible_library=visible_library,
            filtering=filtering,
        )
        return effective

    @staticmethod
    def _inherited_sort_title(
        options: CollectionOptions, policy: CollectionPolicy
    ) -> str | None:
        template = (
            options.sort_title_format
            if options.sort_title_format is not None
            else policy.sort_title_format
        )
        if options.sort_title_format is None and options.sort_title is not None:
            return options.sort_title
        if not template:
            return options.sort_title
        try:
            return format_sort_title(
                template,
                title=options.title,
                group=options.collection_group,
            )
        except ValueError as exc:
            raise PublicServiceError(422, str(exc)) from exc

    @staticmethod
    def _inherited_summary(
        options: CollectionOptions, policy: CollectionPolicy
    ) -> str | None:
        template = (
            options.summary_format
            if options.summary_format is not None
            else policy.summary_format
        )
        if not template:
            return options.summary
        if (
            options.summary_format is None
            and options.summary is not None
            and "{summary}" not in template
        ):
            return options.summary
        try:
            return format_summary(
                template,
                title=options.title,
                group=options.collection_group,
                start_date=options.active_start_mmdd or policy.active_start_mmdd,
                end_date=options.active_end_mmdd or policy.active_end_mmdd,
                summary=options.summary,
            )
        except ValueError as exc:
            raise PublicServiceError(422, str(exc)) from exc

    def _validate_rule_media_type(
        self, media_type: MediaType, body: CollectionRuleWrite
    ) -> None:
        for builder in body.builders:
            if isinstance(builder, TmdbCollectionBuilder | RadarrTagBuilder):
                self._require_movie_collections(media_type)
            elif isinstance(builder, SonarrTagBuilder):
                self._require_show_collections(media_type)
        if (
            body.smart_filter is not None
            and self._provider().server_type is not ServerType.PLEX
        ):
            raise PublicServiceError(
                422, "Smart collections are only supported by Plex"
            )

    async def _prepare_create_rule(
        self,
        body: CollectionCreate,
        policy: CollectionPolicy,
        items: list[MediaItem],
    ) -> tuple[CollectionCreate, CollectionRule | None, list[MediaItem]]:
        if body.rule is None:
            return body, None, items
        self._validate_rule_media_type(body.media_type, body.rule)
        temp_collection = MediaCollection(
            media_type=body.media_type,
            server_type=self._provider().server_type,
            server_item_id="",
            library_id=body.library_id,
            kind=body.kind,
        )
        temp_rule = self._rule_row(0, body.rule)
        for builder in self._rule_builders(temp_rule):
            if (
                isinstance(builder, TmdbPersonBuilder)
                and builder.use_biography
                and body.summary is None
            ):
                person = await self._tmdb.get_person(builder.person_id)
                if person is not None and person.biography:
                    body = body.model_copy(update={"summary": person.biography})
        if temp_rule.builders_json:
            source = await self._source_members(temp_collection, temp_rule)
            source_ids = {item.id for item in source}
            items = (
                source + [item for item in items if item.id not in source_ids]
                if policy.sync_mode is SyncMode.APPEND
                else source
            )
        return body, temp_rule, items

    async def _create_server_collection(
        self,
        body: CollectionCreate,
        temp_rule: CollectionRule | None,
        items: list[MediaItem],
        library_items: list[MediaItem],
        *,
        withhold: bool,
    ) -> tuple[ServerCollection | None, list[MediaItem]]:
        if body.kind is CollectionKind.SMART and (
            body.rule is None or body.rule.smart_filter is None
        ):
            raise PublicServiceError(
                422, "Smart collections require a smart filter configuration"
            )
        if withhold:
            return None, items
        if (
            body.kind is CollectionKind.SMART
            and body.rule is not None
            and body.rule.smart_filter is not None
        ):
            if (
                body.rule.managed_label
                and temp_rule is not None
                and temp_rule.builders_json
            ):
                await self._sync_managed_label(
                    body.library_id,
                    body.media_type,
                    body.rule.managed_label,
                    items,
                    library_items,
                )
            filter_query = compile_plex_smart_filter(
                body.rule.smart_filter,
                managed_label=body.rule.managed_label,
            )
            server = await self._provider().create_smart_collection(
                body.library_id,
                body.title,
                body.media_type,
                filter_query,
            )
            by_server_id = {
                item.server_item_id: item
                for item in library_items
                if item.server_item_id
            }
            matched = [
                by_server_id[sid] for sid in server.member_ids if sid in by_server_id
            ]
            return server, matched
        server = await self._provider().create_collection(
            body.library_id,
            body.title,
            body.media_type,
            [item.server_item_id for item in items if item.server_item_id],
        )
        return server, items

    async def create(self, body: CollectionCreate) -> CollectionDetail:
        """Create on the server, then record its complete local membership."""
        if body.rule is not None:
            overrides = body.model_dump(
                include=body.model_fields_set & _DISPLAY_OVERRIDES
            )
            body = body.model_copy(
                update={"rule": body.rule.model_copy(update=overrides)}
            )
        if body.rule is not None and body.rule.smart_filter is not None:
            body = body.model_copy(update={"kind": CollectionKind.SMART})
        self._validate_options(body)
        if body.tmdb_collection_id is not None:
            self._require_movie_collections(body.media_type)
        library_items = await self._library_items(body.library_id, body.media_type)
        items = self._sort_members(
            self._resolve_members(body.member_ids, library_items),
            body.order_type,
        )
        async with self._database.read_session() as session:
            policy = await self._policy(
                session, body.media_type, body.collection_group, body.rule
            )
        if "order_type" not in body.model_fields_set:
            body = body.model_copy(update={"order_type": policy.order_type})
        body, temp_rule, items = await self._prepare_create_rule(body, policy, items)
        effective_sort_title = self._inherited_sort_title(body, policy)
        effective_summary = self._inherited_summary(body, policy)
        if body.kind is not CollectionKind.SMART and len(items) < policy.minimum_items:
            raise PublicServiceError(
                422, "Collection has fewer members than the effective minimum"
            )
        today = datetime.now(self._app_config.tzinfo).date()
        active = is_within_active_window(
            body.active_start_mmdd or policy.active_start_mmdd,
            body.active_end_mmdd or policy.active_end_mmdd,
            today,
        )
        withhold = not active and policy.delete_when_inactive
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
            server, items = await self._create_server_collection(
                body, temp_rule, items, library_items, withhold=withhold
            )
            now = utc_now()
            fields: dict[str, Any] = body.model_dump(
                exclude={"media_type", "library_id", "member_ids", "rule"}
            )
            fields.update(
                sort_title=effective_sort_title,
                summary=effective_summary,
                summary_source=body.summary,
            )
            row = MediaCollection(
                server_item_id=server.id if server is not None else None,
                server_type=self._provider().server_type,
                media_type=body.media_type,
                library_id=body.library_id,
                child_count=(
                    len(server.member_ids)
                    if body.kind is CollectionKind.SMART and server is not None
                    else len(items)
                ),
                server_link=server.server_link if server is not None else None,
                server_path=server.path if server is not None else None,
                last_synced_at=now,
                created_at=now,
                updated_at=now,
                **fields,
            )
            effective = await self._push_options(row, body, body.rule)
            row.sqlmodel_update(effective.model_dump())
            if (
                body.kind is CollectionKind.REGULAR
                and body.order_type is CollectionOrder.CUSTOM
                and row.server_item_id is not None
            ):
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
                if body.rule is not None:
                    primary_tmdb = self._primary_tmdb_collection_id(body.rule)
                    if primary_tmdb is not None and row.tmdb_collection_id is None:
                        row.tmdb_collection_id = primary_tmdb
                    session.add(self._rule_row(row.id or 0, body.rule))
        await self._publisher.broadcast("collections.changed")
        return await self.get_collection(row.id or 0, body.media_type)

    @staticmethod
    def _primary_tmdb_collection_id(body: CollectionRuleWrite) -> int | None:
        for builder in body.builders:
            if isinstance(builder, TmdbCollectionBuilder):
                return builder.collection_id
        return None

    async def update(
        self, collection_id: int, media_type: MediaType, body: CollectionOptions
    ) -> CollectionDetail:
        """Edit collection metadata without touching movie or show metadata."""
        self._validate_options(body)
        if body.tmdb_collection_id is not None:
            self._require_movie_collections(media_type)
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
            await self._update_locked(row, body)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, media_type)

    async def _update_locked(
        self, row: MediaCollection, body: CollectionOptions
    ) -> None:
        """Persist display choices after the caller acquires the collection locks."""
        overrides: dict[str, object] = {}
        if body.sort_title is not None and body.sort_title_format is None:
            overrides["sort_title_format"] = literal_template(body.sort_title)
        if body.summary is not None and body.summary_format is None:
            overrides["summary_format"] = literal_template(body.summary)
        body = body.model_copy(update=overrides)
        self._validate_options(body)
        if body.summary is not None:
            row.summary_source = body.summary
        display = body.model_dump(include=body.model_fields_set & _DISPLAY_OVERRIDES)
        async with self._database.read_session() as session:
            rule = await CollectionRepository(session).rule(row.id or 0)
        if rule is not None:
            rule.sqlmodel_update(display)
        effective = await self._push_options(row, body, rule)
        summary_source = row.summary_source
        async with self._database.write_session() as session:
            row = await self._require(session, row.id or 0, row.media_type)
            fields = effective.model_dump()
            fields["summary_source"] = summary_source
            if "tmdb_collection_id" not in body.model_fields_set:
                fields.pop("tmdb_collection_id")
            if "kind" not in body.model_fields_set:
                fields.pop("kind")
            row.sqlmodel_update(fields)
            row.updated_at = utc_now()
            session.add(row)
            if rule is not None and display:
                saved_rule = await CollectionRepository(session).rule(row.id or 0)
                if saved_rule is not None:
                    saved_rule.sqlmodel_update(display)
                    session.add(saved_rule)

    async def _delete_server_collection(self, row: MediaCollection) -> None:
        """A server-side deletion is complete when the collection is already absent."""
        if row.server_item_id is not None:
            try:
                await self._provider().delete_collection(row.server_item_id)
            except MediaServerError as exc:
                if exc.upstream_status_code != 404:
                    raise

    async def _delete_locked(
        self, row: MediaCollection, *, server: bool = True
    ) -> None:
        collection_id = row.id or 0
        if server:
            await self._delete_server_collection(row)
        async with self._database.write_session() as session:
            await self._downloads.cancel_assets(
                session, AssetScope(collection_id=collection_id)
            )
            await CollectionRepository(session).delete_ids([collection_id])
        await self._downloads.committed(session)
        await self._publisher.broadcast("collections.changed")

    async def _withhold_locked(self, row: MediaCollection) -> None:
        """Remove a collection from the server while keeping its Overture rule."""
        collection_id = row.id or 0
        await self._delete_server_collection(row)
        async with self._database.write_session() as session:
            current = await CollectionRepository(session).get(collection_id)
            if current is not None:
                current.server_item_id = None
                current.child_count = 0
                current.updated_at = utc_now()
                session.add(current)
            await CollectionRepository(session).replace_members(collection_id, [])
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
        if row.server_item_id is None:
            server = await self._provider().create_collection(
                row.library_id or "",
                row.title,
                row.media_type,
                [item.server_item_id for item in items if item.server_item_id],
            )
            row.server_item_id = server.id
            row.server_link = server.server_link
            row.server_path = server.path
            server_ids = list(server.member_ids)
            if order is CollectionOrder.CUSTOM:
                server_ids = await self._provider().set_collection_members(
                    row.server_item_id,
                    [item.server_item_id for item in items if item.server_item_id],
                    order=order,
                )
        else:
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
            current.server_item_id = row.server_item_id
            current.server_link = row.server_link
            current.server_path = row.server_path
            current.child_count = len(server_ids)
            current.order_type = order
            current.updated_at = utc_now()
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
            if row.kind is CollectionKind.SMART:
                raise PublicServiceError(
                    422, "Smart collection members are controlled by their filter"
                )
            items = self._resolve_members(
                body.member_ids,
                await self._library_items(row.library_id or "", media_type),
            )
            await self._push_options(
                row,
                CollectionOptions(
                    kind=row.kind,
                    title=row.title,
                    summary=row.summary,
                    summary_format=literal_template(row.summary)
                    if row.summary is not None
                    else "",
                    sort_title=row.sort_title,
                    sort_title_format=literal_template(row.sort_title)
                    if row.sort_title is not None
                    else "",
                    collection_group=row.collection_group,
                    collection_mode=row.collection_mode,
                    order_type=body.order_type,
                    collection_filtering=row.collection_filtering,
                    visible_home=row.visible_home,
                    visible_shared=row.visible_shared,
                    visible_library=row.visible_library,
                ),
            )
            await self._set_members_locked(row, items, body.order_type)
        return await self.get_collection(collection_id, media_type)

    @staticmethod
    def _rule_row(collection_id: int, body: CollectionRuleWrite) -> CollectionRule:
        fields = body.model_dump(exclude={"builders", "smart_filter"})
        return CollectionRule(
            collection_id=collection_id,
            builders_json=(
                builders_adapter.dump_json(body.builders).decode()
                if body.builders
                else None
            ),
            smart_filter_json=(
                body.smart_filter.model_dump_json()
                if body.smart_filter is not None
                else None
            ),
            **fields,
        )

    async def save_rule(
        self, collection_id: int, media_type: MediaType, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        """Persist validated rule settings; polling sees them after commit."""
        self._validate_rule_media_type(media_type, body)
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require(session, collection_id, media_type)
                existing = await CollectionRepository(session).rule(collection_id)
            use_source_order = (
                existing is None
                and body.order_type is None
                and any(isinstance(b, MdblistBuilder) for b in body.builders)
                and row.server_type is ServerType.PLEX
            )
            if use_source_order:
                body = body.model_copy(update={"order_type": CollectionOrder.CUSTOM})
                await self._push_options(
                    row,
                    CollectionOptions(
                        kind=row.kind,
                        title=row.title,
                        summary=row.summary,
                        summary_format=literal_template(row.summary)
                        if row.summary is not None
                        else "",
                        sort_title=row.sort_title,
                        sort_title_format=literal_template(row.sort_title)
                        if row.sort_title is not None
                        else "",
                        collection_group=row.collection_group,
                        collection_mode=row.collection_mode,
                        order_type=CollectionOrder.CUSTOM,
                        collection_filtering=row.collection_filtering,
                        visible_home=row.visible_home,
                        visible_shared=row.visible_shared,
                        visible_library=row.visible_library,
                    ),
                    body,
                )
            async with self._database.write_session() as session:
                await self._require(session, collection_id, media_type)
                rule = await CollectionRepository(session).rule(collection_id)
                new_row = self._rule_row(collection_id, body)
                fields = new_row.model_dump(exclude={"id", "collection_id"})
                if rule is None:
                    rule = new_row
                else:
                    rule.sqlmodel_update(fields)
                rule.last_error = None
                rule.last_synced_at = None
                session.add(rule)
                primary_tmdb = self._primary_tmdb_collection_id(body)
                if (
                    use_source_order
                    or primary_tmdb is not None
                    or body.smart_filter is not None
                ):
                    row = await self._require(session, collection_id, media_type)
                    if use_source_order:
                        row.order_type = CollectionOrder.CUSTOM
                    if primary_tmdb is not None:
                        row.tmdb_collection_id = primary_tmdb
                    if body.smart_filter is not None:
                        row.kind = CollectionKind.SMART
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

    async def _resolve_builder(
        self,
        row: MediaCollection,
        builder: CollectionBuilder,
        items: list[MediaItem],
    ) -> list[MediaItem]:
        if isinstance(builder, LibraryFilterBuilder):
            return evaluate_filter_group(items, builder.filter_group)
        if isinstance(builder, RadarrTagBuilder):
            matches = await self._radarr.external_ids_for_tags(builder.tags)
            tmdb_set = set(matches.tmdb_ids)
            imdb_set = set(matches.imdb_ids)
            return [
                item
                for item in items
                if (item.tmdb_id is not None and item.tmdb_id in tmdb_set)
                or (item.imdb_id is not None and item.imdb_id in imdb_set)
            ]
        if isinstance(builder, SonarrTagBuilder):
            matches = await self._sonarr.external_ids_for_tags(builder.tags)
            tmdb_set = set(matches.tmdb_ids)
            tvdb_set = set(matches.tvdb_ids)
            imdb_set = set(matches.imdb_ids)
            return [
                item
                for item in items
                if (item.tmdb_id is not None and item.tmdb_id in tmdb_set)
                or (item.tvdb_id is not None and item.tvdb_id in tvdb_set)
                or (item.imdb_id is not None and item.imdb_id in imdb_set)
            ]
        if isinstance(builder, MdblistBuilder):
            ids: list[int] = []
            for identifier in builder.identifiers:
                ids.extend(await self._mdblist.tmdb_ids(identifier, row.media_type))
        elif isinstance(builder, TmdbListBuilder):
            ids = []
            for list_id in builder.list_ids:
                ids.extend(await self._tmdb.get_list_ids(list_id, row.media_type))
        elif isinstance(builder, TmdbItemBuilder):
            ids = list(builder.tmdb_ids)
        elif isinstance(builder, TmdbPersonBuilder):
            ids = list(
                await self._tmdb.get_person_credits(
                    builder.person_id, row.media_type, set(builder.roles)
                )
            )
        else:
            franchise = await self._tmdb.get_collection(builder.collection_id)
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
        rank: dict[int, int] = {}
        for index, tmdb_id in enumerate(ids):
            rank.setdefault(tmdb_id, index)
        return sorted(
            [item for item in items if item.tmdb_id in rank],
            key=lambda item: (rank[item.tmdb_id or 0], item.id or 0),
        )

    async def _source_members(
        self, row: MediaCollection, rule: CollectionRule
    ) -> list[MediaItem]:
        async with self._database.read_session() as session:
            items = await CollectionRepository(session).library_items(
                row.media_type, row.library_id or ""
            )
        builders = self._rule_builders(rule)
        if not builders:
            return []
        combined: dict[int, MediaItem] = {}
        for builder in builders:
            for item in await self._resolve_builder(row, builder, items):
                if item.id is not None:
                    combined.setdefault(item.id, item)
        return list(combined.values())

    async def _sync_managed_label(
        self,
        library_id: str,
        media_type: MediaType,
        label: str,
        wanted: list[MediaItem],
        library_items: list[MediaItem],
    ) -> None:
        wanted_server_ids = {
            item.server_item_id for item in wanted if item.server_item_id
        }
        currently_labeled = {
            item.server_item_id
            for item in library_items
            if item.server_item_id
            and any(existing.casefold() == label.casefold() for existing in item.labels)
        }
        add_ids = sorted(wanted_server_ids - currently_labeled)
        remove_ids = sorted(currently_labeled - wanted_server_ids)
        if not add_ids and not remove_ids:
            return
        await self._provider().sync_item_labels(
            library_id,
            media_type,
            label,
            add_ids=add_ids,
            remove_ids=remove_ids,
        )
        async with self._database.write_session() as session:
            for item in await CollectionRepository(session).library_items(
                media_type, library_id
            ):
                if item.server_item_id in add_ids:
                    if not any(
                        existing.casefold() == label.casefold()
                        for existing in item.labels
                    ):
                        item.labels = [*item.labels, label]
                        session.add(item)
                elif item.server_item_id in remove_ids:
                    item.labels = [
                        existing
                        for existing in item.labels
                        if existing.casefold() != label.casefold()
                    ]
                    session.add(item)

    async def _sync_smart_rule_locked(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        collection_id = row.id or 0
        media_type = row.media_type
        smart_filter = self._rule_smart_filter(rule)
        if smart_filter is None:
            raise PublicServiceError(
                422, "Smart collection has no filter configuration"
            )
        if rule.builders_json and rule.managed_label:
            wanted_labeled = await self._source_members(row, rule)
            await self._sync_managed_label(
                row.library_id or "",
                media_type,
                rule.managed_label,
                wanted_labeled,
                library_items,
            )
        filter_query = compile_plex_smart_filter(
            smart_filter, managed_label=rule.managed_label
        )
        if row.server_item_id is None:
            server = await self._provider().create_smart_collection(
                row.library_id or "",
                row.title,
                media_type,
                filter_query,
            )
            row.server_item_id = server.id
            row.server_link = server.server_link
        else:
            await self._provider().update_smart_collection_filter(
                row.server_item_id,
                row.library_id or "",
                media_type,
                filter_query,
            )
        await self._update_locked(
            row,
            CollectionOptions(
                kind=CollectionKind.SMART,
                title=row.title,
                summary=None,
                summary_format=row.summary_format,
                sort_title=None,
                sort_title_format=row.sort_title_format,
                collection_group=row.collection_group,
                active_start_mmdd=row.active_start_mmdd,
                active_end_mmdd=row.active_end_mmdd,
                delete_when_inactive=row.delete_when_inactive,
            ),
        )
        remote_ids = await self._provider().get_collection_member_ids(
            row.server_item_id
        )
        by_server_id = {
            item.server_item_id: item for item in library_items if item.server_item_id
        }
        stored_ids = [
            by_server_id[sid].id or 0 for sid in remote_ids if sid in by_server_id
        ]
        old_ids = {item.id or 0 for item in current}
        new_ids = set(stored_ids)
        async with self._database.write_session() as session:
            saved_row = await self._require(session, collection_id, media_type)
            await CollectionRepository(session).replace_members(
                collection_id, stored_ids
            )
            saved_row.server_item_id = row.server_item_id
            saved_row.server_link = row.server_link
            saved_row.kind = CollectionKind.SMART
            saved_row.child_count = len(remote_ids)
            saved_row.updated_at = utc_now()
            session.add(saved_row)
        return CollectionSyncResponse(
            added=len(new_ids - old_ids),
            removed=len(old_ids - new_ids),
        )

    async def _sync_regular_rule_locked(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        wanted = await self._source_members(row, rule)
        if rule.managed_label and self._provider().server_type is ServerType.PLEX:
            await self._sync_managed_label(
                row.library_id or "",
                row.media_type,
                rule.managed_label,
                wanted,
                library_items,
            )
        mode = policy.sync_mode
        member_count = len(wanted)
        if mode is SyncMode.APPEND and row.server_item_id is not None:
            remote_ids = await self._provider().get_collection_member_ids(
                row.server_item_id
            )
            member_count = len(
                set(remote_ids) | {item.server_item_id for item in wanted}
            )
        if member_count < policy.minimum_items:
            if policy.delete_below_minimum:
                await self._delete_locked(row)
                return CollectionSyncResponse(deleted=True, removed=len(current))
            return CollectionSyncResponse(skipped=True)
        old = {item.id for item in current}
        new = {item.id for item in wanted}
        effective_order = policy.order_type
        await self._set_members_locked(
            row,
            wanted,
            effective_order,
            append=mode is SyncMode.APPEND,
        )
        await self._update_locked(
            row,
            CollectionOptions(
                kind=row.kind,
                title=row.title,
                summary=None,
                summary_format=row.summary_format,
                sort_title=None,
                sort_title_format=row.sort_title_format,
                collection_group=row.collection_group,
                active_start_mmdd=row.active_start_mmdd,
                active_end_mmdd=row.active_end_mmdd,
                delete_when_inactive=row.delete_when_inactive,
            ),
        )
        return CollectionSyncResponse(
            added=len(new - old),
            removed=len(old - new) if mode is SyncMode.SYNC else 0,
        )

    async def _execute_rule_sync(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
        *,
        active: bool,
    ) -> CollectionSyncResponse:
        if not active:
            if policy.delete_when_inactive and row.server_item_id is not None:
                await self._withhold_locked(row)
                return CollectionSyncResponse(deleted=True, removed=len(current))
            return CollectionSyncResponse(skipped=True)
        if row.kind is CollectionKind.SMART or rule.smart_filter_json is not None:
            return await self._sync_smart_rule_locked(row, rule, current, library_items)
        return await self._sync_regular_rule_locked(
            row, rule, policy, current, library_items
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
                policy = await self._policy(
                    session, media_type, row.collection_group, rule
                )
                current = await CollectionRepository(session).members(collection_id)
                library_items = await CollectionRepository(session).library_items(
                    media_type, row.library_id or ""
                )
            if rule is None:
                raise PublicServiceError(404, "Collection has no dynamic rule")
            if scheduled and (
                not policy.sync_enabled
                or policy.sync_interval_hours <= 0
                or (
                    rule.last_synced_at is not None
                    and utc_now()
                    < rule.last_synced_at + timedelta(hours=policy.sync_interval_hours)
                )
            ):
                return CollectionSyncResponse(skipped=True)
            error = None
            try:
                today = datetime.now(self._app_config.tzinfo).date()
                active = is_within_active_window(
                    row.active_start_mmdd or policy.active_start_mmdd,
                    row.active_end_mmdd or policy.active_end_mmdd,
                    today,
                )
                result = await self._execute_rule_sync(
                    row, rule, policy, current, library_items, active=active
                )
                if result.deleted and active:
                    return result
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
        if not result.skipped and not result.deleted:
            await self._run_post_sync_assets(collection_id, media_type)
        return result

    async def _run_post_sync_assets(
        self, collection_id: int, media_type: MediaType
    ) -> None:
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

    async def _auto_assets(self, collection_id: int, media_type: MediaType) -> None:
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
            policy = await self._policy(session, media_type, row.collection_group, rule)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
                app_config=self._app_config,
            )
        if row.server_item_id is None:
            return
        if policy.auto_match_art and row.tmdb_collection_id is not None:
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
            policy.auto_match_theme
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

    async def _policy(
        self,
        session: AsyncSession,
        media_type: MediaType,
        group: str | None,
        rule: RuleOrPolicy = None,
    ) -> CollectionPolicy:
        return resolve_policy(
            await get_app_settings(session),
            await CollectionRepository(session).group_policy(
                self._provider().server_type, media_type, group
            ),
            rule,
        )

    async def inherited_policy(
        self, media_type: MediaType, name: str | None = None
    ) -> CollectionPolicyBase:
        """Expose resolved defaults for form placeholders without duplicating rules."""
        async with self._database.read_session() as session:
            policy = await self._policy(session, media_type, name)
        return CollectionPolicyBase.model_validate(
            {key: getattr(policy, key) for key in CollectionPolicyBase.model_fields}
        )

    async def preview_preset(
        self, body: CollectionPresetPreview
    ) -> list[CollectionPresetEntry]:
        """Preview collections using only the selected library's active items."""
        return preview_preset(
            body.preset, await self._library_items(body.library_id, body.media_type)
        )

    async def create_preset(
        self, body: CollectionPresetCreate
    ) -> CollectionPresetResult:
        """Commit each preset entry independently through the regular workflow."""
        entries = {entry.key: entry for entry in await self.preview_preset(body)}
        if not set(body.keys) <= entries.keys():
            raise PublicServiceError(
                422,
                "Preview the library again; a selected value is no longer available",
            )
        metadata = set(CollectionOptions.model_fields)
        options = body.policy.model_dump(include=metadata, exclude_none=True)
        rule_defaults = body.policy.model_dump(exclude=metadata)
        result = CollectionPresetResult()
        for key in dict.fromkeys(body.keys):
            entry = entries[key]
            try:
                created = await self.create(
                    CollectionCreate(
                        title=entry.title,
                        media_type=body.media_type,
                        library_id=body.library_id,
                        collection_group=body.collection_group,
                        **options,
                        rule=CollectionRuleWrite(
                            **rule_defaults,
                            builders=[entry.builder],
                            enabled=body.enabled,
                            sync_interval_hours=body.sync_interval_hours,
                        ),
                    )
                )
                result.collection_ids.append(created.id)
            except Exception as exc:
                result.errors[key] = sanitise_error(str(exc))
        return result

    async def rename_group(
        self, media_type: MediaType, name: str, replacement: str
    ) -> StatusResponse:
        """Rename defaults and every member atomically, including unlisted rows."""
        name, replacement = name.strip(), replacement.strip()
        if not replacement:
            raise PublicServiceError(422, "A group needs a name")
        server = self._provider().server_type
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._database.write_session() as session,
        ):
            repo = CollectionRepository(session)
            group = await repo.group_policy(server, media_type, name)
            rows = await repo.group_members(server, media_type, name)
            if group is None and not rows:
                raise PublicServiceError(404, "Collection group not found")
            if replacement != name and (
                await repo.group_policy(server, media_type, replacement) is not None
                or await repo.group_members(server, media_type, replacement)
            ):
                raise PublicServiceError(
                    409, "A collection group with this name already exists"
                )
            if group is not None:
                group.name = replacement
                session.add(group)
            for row in rows:
                row.collection_group = replacement
                row.updated_at = utc_now()
                session.add(row)
        await self._publisher.broadcast("collections.changed")
        return StatusResponse(status=Status.OK)

    async def delete_group(
        self, media_type: MediaType, name: str, body: CollectionGroupDelete
    ) -> BulkCollectionOperationResult:
        """Remove a group only after each selected collection operation succeeds."""
        name = name.strip()
        server = self._provider().server_type
        result = BulkCollectionOperationResult()
        async with self._downloads.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._database.read_session() as session:
                repo = CollectionRepository(session)
                rows = await repo.group_members(server, media_type, name)
                group = await repo.group_policy(server, media_type, name)
            if group is None and not rows:
                raise PublicServiceError(404, "Collection group not found")
            for row in rows:
                identity = row.id or 0
                try:
                    async with self._downloads.asset_locks.acquire(
                        f"collection:{identity}"
                    ):
                        if body.collections in {"overture", "both"}:
                            await self._delete_locked(
                                row, server=body.collections == "both"
                            )
                        elif body.collections == "server":
                            await self._withhold_locked(row)
                            async with self._database.write_session() as session:
                                rule = await CollectionRepository(session).rule(
                                    identity
                                )
                                if rule is not None:
                                    rule.enabled = False
                                    session.add(rule)
                    result.collection_ids.append(identity)
                except Exception as exc:
                    result.errors[identity] = sanitise_error(str(exc))
            if not result.errors:
                async with self._database.write_session() as session:
                    repo = CollectionRepository(session)
                    for row in await repo.group_members(server, media_type, name):
                        row.collection_group = None
                        row.updated_at = utc_now()
                        session.add(row)
                    group = await repo.group_policy(server, media_type, name)
                    if group is not None:
                        await session.delete(group)
        await self._publisher.broadcast("collections.changed")
        return result

    async def group_policy(
        self, media_type: MediaType, name: str
    ) -> CollectionGroupPolicy:
        """Return nullable group overrides, including for a new group."""
        async with self._database.read_session() as session:
            row = await CollectionRepository(session).group_policy(
                self._provider().server_type, media_type, name.strip()
            )
        if row is None:
            return CollectionGroupPolicy()
        dynamic_tmdb = (
            DynamicTmdbGroupConfig.model_validate_json(row.dynamic_tmdb_json)
            if row.dynamic_tmdb_json
            else None
        )
        data = row.model_dump(
            exclude={"id", "server_type", "media_type", "name", "dynamic_tmdb_json"}
        )
        return CollectionGroupPolicy(**data, dynamic_tmdb=dynamic_tmdb)

    async def save_group_policy(
        self, media_type: MediaType, name: str, body: CollectionGroupPolicy
    ) -> CollectionGroupPolicy:
        """Save group defaults without replacing explicit collection overrides."""
        name = name.strip()
        if not name:
            raise PublicServiceError(422, "A group needs a name")
        if self._provider().server_type is not ServerType.PLEX and (
            body.collection_mode not in {None, CollectionMode.DEFAULT}
            or body.visible_home
            or body.visible_shared
            or body.visible_library
            or body.collection_filtering is not None
        ):
            raise PublicServiceError(422, "Collection visibility requires Plex")
        if body.dynamic_tmdb is not None and media_type is not MediaType.MOVIE:
            raise PublicServiceError(
                422, "Dynamic TMDB franchise discovery is only available for movies"
            )
        async with self._database.write_session() as session:
            row = await CollectionRepository(session).group_policy(
                self._provider().server_type, media_type, name
            )
            if row is None:
                row = CollectionGroup(
                    server_type=self._provider().server_type,
                    media_type=media_type,
                    name=name,
                )
            fields = body.model_dump(exclude={"dynamic_tmdb"})
            fields["dynamic_tmdb_json"] = (
                body.dynamic_tmdb.model_dump_json()
                if body.dynamic_tmdb is not None
                else None
            )
            row.sqlmodel_update(fields)
            session.add(row)
        await self._publisher.broadcast("collections.changed")
        return body

    async def apply_group_policy(
        self, media_type: MediaType, name: str
    ) -> BulkCollectionOperationResult:
        """Apply display defaults while preserving sources and rule overrides."""
        async with self._database.read_session() as session:
            ids = [
                row.id
                for row in await CollectionRepository(session).list_listed(media_type)
                if row.collection_group == name
                and row.server_type is self._provider().server_type
                and row.id is not None
            ]
        result = BulkCollectionOperationResult()
        for collection_id in ids:
            try:
                async with (
                    self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
                    self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
                ):
                    async with self._database.read_session() as session:
                        row = await self._require(session, collection_id, media_type)
                        rule = await CollectionRepository(session).rule(collection_id)
                    if row.collection_group != name:
                        continue
                    await self._update_locked(row, self._saved_options(row, rule))
                result.collection_ids.append(collection_id)
                await self._publisher.broadcast(
                    "collection.updated", {"collection_id": collection_id}
                )
            except Exception as exc:
                result.errors[collection_id] = sanitise_error(str(exc))
        return result

    async def sync_group(self, media_type: MediaType, name: str) -> GroupSyncResult:
        """Run dynamic TMDB discovery (if enabled) and sync rules in *name*."""
        name = name.strip()
        async with self._database.read_session() as session:
            group = await CollectionRepository(session).group_policy(
                self._provider().server_type, media_type, name
            )
        response = GroupSyncResult()
        if group is not None and group.dynamic_tmdb_json:
            config = DynamicTmdbGroupConfig.model_validate_json(group.dynamic_tmdb_json)
            if config.enabled:
                discovered = await self._sync_dynamic_tmdb_group(group, config)
                response.created.extend(discovered.created)
                response.errors.update(discovered.errors)
        async with self._database.read_session() as session:
            rows = [
                row
                for row in await CollectionRepository(session).list_listed(media_type)
                if row.server_type is self._provider().server_type
                and row.collection_group == name
                and row.id is not None
            ]
            rules = {
                rule.collection_id: rule
                for rule in await CollectionRepository(session).rules(
                    enabled_only=False
                )
            }
        for row in rows:
            if (
                row.id is not None
                and row.id in rules
                and row.id not in response.created
            ):
                try:
                    await self.sync_rule(row.id, media_type)
                except Exception as exc:
                    response.errors[row.title] = sanitise_error(str(exc))
        return response

    def _dynamic_tmdb_exclusions(
        self,
        group_name: str,
        config: DynamicTmdbGroupConfig,
        existing: list[MediaCollection],
        rules: list[CollectionRule],
    ) -> tuple[set[int], set[int]]:
        existing_by_id = {row.id: row for row in existing if row.id is not None}
        excluded_ids: set[int] = set(config.exclude_tmdb_ids)
        in_group_tmdb_ids: set[int] = set()
        for row in existing:
            tmdb_id = row.tmdb_collection_id or row.auto_generated_tmdb_id
            if tmdb_id is None:
                continue
            if row.collection_group == group_name:
                in_group_tmdb_ids.add(tmdb_id)
            elif config.auto_exclude_from_other_collections:
                excluded_ids.add(tmdb_id)
        if config.auto_exclude_from_other_collections:
            for rule in rules:
                owner = existing_by_id.get(rule.collection_id)
                if owner is None or owner.collection_group == group_name:
                    continue
                for builder in self._rule_builders(rule):
                    if isinstance(builder, TmdbCollectionBuilder):
                        excluded_ids.add(builder.collection_id)
        return excluded_ids, in_group_tmdb_ids

    async def _sync_dynamic_tmdb_group(
        self,
        group: CollectionGroup,
        config: DynamicTmdbGroupConfig,
    ) -> GroupSyncResult:
        """Auto-discover and sync TMDB franchise collections for *group*."""
        items = await self._library_items(config.library_id, MediaType.MOVIE)
        async with self._database.read_session() as session:
            policy = await self._policy(session, MediaType.MOVIE, group.name)
            existing = [
                row
                for row in await CollectionRepository(session).list_listed(
                    MediaType.MOVIE
                )
                if row.library_id == config.library_id
                and row.server_type is self._provider().server_type
            ]
            rules = await CollectionRepository(session).rules(enabled_only=False)
        excluded_ids, in_group_tmdb_ids = self._dynamic_tmdb_exclusions(
            group.name, config, existing, rules
        )
        used_titles = {row.title.casefold() for row in existing}
        counts: dict[int, int] = {}
        for item in items:
            if item.tmdb_collection_id is not None:
                counts[item.tmdb_collection_id] = (
                    counts.get(item.tmdb_collection_id, 0) + 1
                )

        response = GroupSyncResult()
        for tmdb_id, count in sorted(counts.items()):
            if (
                tmdb_id in excluded_ids
                or tmdb_id in in_group_tmdb_ids
                or count < policy.minimum_items
            ):
                continue
            franchise = await self._tmdb.get_collection(tmdb_id)
            if franchise is None:
                continue
            source_ids = {part.tmdb_id for part in franchise.parts}
            matched_count = sum(item.tmdb_id in source_ids for item in items)
            if matched_count < policy.minimum_items:
                continue
            title = strip_affixes(
                franchise.title,
                prefix=config.strip_prefix,
                suffix=config.strip_suffix,
            )
            if title.casefold() in used_titles:
                continue
            try:
                detail = await self.create(
                    CollectionCreate(
                        title=title,
                        collection_group=group.name,
                        tmdb_collection_id=tmdb_id,
                        library_id=config.library_id,
                        media_type=MediaType.MOVIE,
                        rule=CollectionRuleWrite(
                            builders=[TmdbCollectionBuilder(collection_id=tmdb_id)],
                        ),
                    )
                )
                async with self._database.write_session() as session:
                    created_row = await CollectionRepository(session).get(detail.id)
                    if created_row is not None:
                        created_row.auto_generated_tmdb_id = tmdb_id
                        session.add(created_row)
                used_titles.add(title.casefold())
                response.created.append(detail.id)
                await self._auto_assets(detail.id, MediaType.MOVIE)
            except Exception as exc:
                response.errors[title] = sanitise_error(str(exc))
        return response

    @staticmethod
    def _saved_options(
        row: MediaCollection, rule: CollectionRule | None
    ) -> CollectionOptions:
        options = CollectionOptions(
            kind=row.kind,
            title=row.title,
            collection_group=row.collection_group,
            tmdb_collection_id=row.tmdb_collection_id,
            sort_title_format=row.sort_title_format,
            summary_format=row.summary_format,
            active_start_mmdd=row.active_start_mmdd,
            active_end_mmdd=row.active_end_mmdd,
            delete_when_inactive=row.delete_when_inactive,
        )
        if rule is None:
            # Imported server display choices remain explicit.
            options = options.model_copy(
                update={
                    **row.model_dump(include=set(_DISPLAY_OVERRIDES)),
                    "summary": row.summary if row.summary_format is None else None,
                    "sort_title": row.sort_title
                    if row.sort_title_format is None
                    else None,
                }
            )
        return options

    @staticmethod
    def _apply_bulk_option(
        row: MediaCollection,
        body: BulkCollectionOperation,
        rule: CollectionRule | None,
    ) -> CollectionOptions:
        options = CollectionsService._saved_options(row, rule)
        if body.operation == "set_group":
            options.collection_group = (
                body.collection_group.strip() or None if body.collection_group else None
            )
        elif body.operation == "set_order" and body.order_type is not None:
            options.order_type = body.order_type
        elif body.operation == "set_visibility":
            if "collection_mode" in body.model_fields_set:
                options.collection_mode = body.collection_mode
            if body.visible_home is not None:
                options.visible_home = body.visible_home
            if body.visible_shared is not None:
                options.visible_shared = body.visible_shared
            if body.visible_library is not None:
                options.visible_library = body.visible_library
        elif body.sort_title_format is not None:
            options.sort_title = None
            options.sort_title_format = body.sort_title_format
        return options

    async def bulk_operation(
        self, body: BulkCollectionOperation
    ) -> BulkCollectionOperationResult:
        """Use the single-collection workflows, committing each target independently."""
        result = BulkCollectionOperationResult()
        for collection_id in body.collection_ids:
            try:
                if body.operation == "delete":
                    await self.delete(collection_id, body.media_type)
                elif body.operation == "trigger_sync":
                    await self.sync_rule(collection_id, body.media_type)
                elif body.operation == "set_monitored":
                    await self.set_collection_monitored(
                        collection_id, body.media_type, bool(body.monitored)
                    )
                else:
                    # Keep the read and update under the same asset locks.
                    async with (
                        self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
                        self._downloads.asset_locks.acquire(
                            f"collection:{collection_id}"
                        ),
                    ):
                        async with self._database.read_session() as session:
                            row = await self._require(
                                session, collection_id, body.media_type
                            )
                            rule = await CollectionRepository(session).rule(
                                collection_id
                            )
                        await self._update_locked(
                            row, self._apply_bulk_option(row, body, rule)
                        )
                    await self._publisher.broadcast(
                        "collection.updated", {"collection_id": collection_id}
                    )
                result.collection_ids.append(collection_id)
            except Exception as exc:
                result.errors[collection_id] = sanitise_error(str(exc))
        return result

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
            defaults = await get_app_settings(session)
            groups = {
                group.name: group
                for group in await CollectionRepository(session).group_policies(
                    self._provider().server_type, media_type
                )
            }
            rules = {
                rule.collection_id: rule
                for rule in await CollectionRepository(session).rules(
                    enabled_only=False
                )
            }
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id for row in rows if row.tmdb_collection_id},
                app_config=self._app_config,
            )
        return [
            collection_read(row, catalog.get(row.tmdb_collection_id or 0)).model_copy(
                update={
                    "below_minimum": row.child_count
                    < resolve_policy(
                        defaults,
                        groups.get(row.collection_group or ""),
                        rules.get(row.id or 0),
                    ).minimum_items
                }
            )
            for row in rows
            if row.server_type is self._provider().server_type
        ]

    async def groups(self, media_type: MediaType) -> list[str]:
        """Return preset groups and custom groups used on the active server."""
        provider = self._provider()
        async with self._database.read_session() as session:
            rows = await CollectionRepository(session).list_listed(media_type)
            policies = await CollectionRepository(session).group_policies(
                provider.server_type, media_type
            )
        return sorted(
            {group.name for group in policies}
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
            policy = await self._policy(session, media_type, row.collection_group, rule)
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
            **collection_read(row, entry)
            .model_copy(
                update={"below_minimum": row.child_count < policy.minimum_items}
            )
            .model_dump(),
            effective_sync_mode=policy.sync_mode,
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
        if row is None or row.server_item_id is None:
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

    @staticmethod
    def _require_movie_collections(media_type: MediaType) -> None:
        if media_type is not MediaType.MOVIE:
            raise PublicServiceError(
                422, "TMDB collections and Radarr tags are only available for movies"
            )

    @staticmethod
    def _require_show_collections(media_type: MediaType) -> None:
        if media_type is not MediaType.SHOW:
            raise PublicServiceError(422, "Sonarr tags are only available for TV shows")

    async def proxy_collection_image(
        self, collection_id: int, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy a collection's poster or background with bounded response size."""
        provider = self._provider()
        if art_type.owned_by_season:
            raise PublicServiceError(404, "Collection image not found")
        async with self._database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None or row.last_synced_at is None or row.server_item_id is None:
            raise PublicServiceError(404, "Collection not found")
        request = await provider.build_collection_image_request(
            row.server_item_id, art_type, size
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
