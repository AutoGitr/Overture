"""Collection service operations."""

lazy import logging
lazy import urllib.parse
lazy from collections import Counter
lazy from collections.abc import Awaitable, Callable, Mapping
lazy from contextlib import suppress
lazy from datetime import datetime
lazy from pathlib import Path

lazy from fastapi import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.art_slots import clear_art_selection, find_art_slot, read_art_slot
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_preset import CollectionPreset
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetCollection
lazy from ...db.models.settings import AppSettings, get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import record_theme_file
lazy from ...domain import (
    ITEM_ART_TYPES,
    SMART_CUSTOM_ORDER,
    UNGROUPED_GROUP,
    UNMANAGED_REFUSAL,
    ArtType,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    FilterField,
    FilterOperator,
    ImageSize,
    MediaType,
    ServerType,
    SetDimension,
    SourceType,
    SyncMode,
    TmdbChart,
)
lazy from ...integrations.arr import ArrClient
lazy from ...integrations.mdblist import MDBListClient
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...integrations.tmdb import TMDBClient, chart_available
lazy from ...jobs.gate import LibraryGate
lazy from ...media_servers.adapters import UploadThemes
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.collections import (
    ArrTagRead,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionArrOptions,
    CollectionCapabilities,
    CollectionCreate,
    CollectionDeleteTarget,
    CollectionDetail,
    CollectionDimensionRead,
    CollectionFieldRead,
    CollectionFieldValue,
    CollectionGenerator,
    CollectionGeneratorBase,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupSyncResult,
    CollectionMembersUpdate,
    CollectionMissing,
    CollectionOptions,
    CollectionPolicyBase,
    CollectionPresetRead,
    CollectionPresetSave,
    CollectionPreview,
    CollectionPreviewRequest,
    CollectionRead,
    CollectionRequest,
    CollectionRequestResult,
    CollectionRuleRead,
    CollectionRuleWrite,
    CollectionSetEntry,
    CollectionSetPreview,
    CollectionSourceRead,
    CollectionSyncResponse,
    CollectionTakeOver,
    CollectionThemeStatusResponse,
    Condition,
    DeleteCollectionThemeResponse,
    FieldCondition,
    FilterGroup,
    KindRecommendation,
    SetCollectionThemeRequest,
    SourceCondition,
    TmdbChartSource,
    TmdbCollectionSource,
    TmdbItemSource,
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
lazy from ...schemas.validators import check_group_name
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.collection_formats import (
    format_member_tag,
    format_sort_title,
    format_summary,
    is_within_active_window,
    literal_template,
)
lazy from ...utils.collection_groups import collection_group
lazy from ...utils.cron import next_run_after
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import has_incorrect_aspect_ratio
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
lazy from .criteria import CriteriaContext, evaluate, field_value, order_items
lazy from .fields import (
    DIMENSIONS,
    FIELDS,
    OPERATORS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
    smart_only_dimension,
)
lazy from .member_effects import MemberEffects
lazy from .plex_query import (
    UnmappableFilterError,
    choice_keys,
    compile_plex_query,
    decompile_plex_query,
    plex_field,
    plex_field_keys,
    tag_keys,
)
lazy from .policy import CollectionPolicy, RuleOrPolicy, resolve_policy
lazy from .presets import available_presets, saved_preset_read
lazy from .recommend import recommend_kind
lazy from .sets import SetValue, count_values, set_values
lazy from .sources import (
    SOURCE_LABEL_PREFIX,
    SOURCE_LABELS,
    SourceResolver,
    source_label,
)

logger = logging.getLogger(__name__)

_TITLE_TAKEN = "A collection with this title already exists in this library"

#: Sources whose order is meaningful, which a new rule keeps by default.
_ORDERED_SOURCES = frozenset(
    {SourceType.MDBLIST, SourceType.TMDB_LIST, SourceType.TMDB_ITEM}
)


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


def _by_label(
    option: CollectionFieldRead | CollectionSourceRead | CollectionDimensionRead,
) -> str:
    """Dropdowns list options alphabetically within their group."""
    return option.label.casefold()


def _criteria(rule: CollectionRule) -> FilterGroup:
    return FilterGroup.model_validate_json(rule.criteria_json)


def _rule_read(rule: CollectionRule | None) -> CollectionRuleRead | None:
    if rule is None:
        return None
    return CollectionRuleRead(
        **rule.model_dump(
            exclude={"id", "collection_id", "criteria_json", "smart", "item_limit"}
        ),
        criteria=_criteria(rule),
        smart=rule.smart,
        limit=rule.item_limit,
    )


def _rule_row(collection_id: int, body: CollectionRuleWrite) -> CollectionRule:
    return CollectionRule(
        collection_id=collection_id,
        criteria_json=body.criteria.model_dump_json(),
        item_limit=body.limit,
        **body.model_dump(exclude={"criteria", "limit"}),
    )


def _outdates_server(row: MediaCollection) -> bool:
    """A local save outdates a server copy; a seasonally withheld one has none."""
    return row.unsynced or row.server_item_id is not None


def _never_created(row: MediaCollection) -> bool:
    """Saved in Overture only, so the scheduler leaves it until it is synced."""
    return row.unsynced and row.server_item_id is None


def _member_criteria(row: MediaCollection, members: list[MediaItem]) -> FilterGroup:
    """Criteria that select exactly a collection's current members.

    Members are named by TMDB ID where they have one, else by title.
    """
    tmdb_ids = [item.tmdb_id for item in members if item.tmdb_id is not None]
    conditions: list[Condition] = [
        FieldCondition(field=FilterField.TITLE, value=item.title)
        for item in members
        if item.tmdb_id is None
    ]
    if tmdb_ids:
        conditions.insert(0, SourceCondition(source=TmdbItemSource(tmdb_ids=tmdb_ids)))
    if not conditions:
        raise PublicServiceError(422, f"{row.title} has no members to keep")
    return FilterGroup(mode="any", conditions=conditions)


def _group_name(name: str) -> str:
    """Return a stored group's name, stripped, refusing empty or reserved ones.

    Raises:
        PublicServiceError: 422 for an empty or reserved name.
    """
    name = name.strip()
    if not name:
        raise PublicServiceError(422, "A group needs a name")
    try:
        return check_group_name(name)
    except ValueError as exc:
        raise PublicServiceError(422, str(exc)) from exc


def _generator(group: CollectionGroup | None) -> CollectionGenerator | None:
    if group is None or not group.generator_json:
        return None
    return CollectionGenerator.model_validate_json(group.generator_json)


def _franchise_ids(criteria: FilterGroup) -> set[int]:
    return {
        condition.source.collection_id
        for condition in criteria.source_conditions()
        if isinstance(condition.source, TmdbCollectionSource)
        and condition.operator is FilterOperator.IS
    }


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
        self._scheduler = scheduler
        self._art = art
        self._sources = SourceResolver(
            app_config=app_config,
            tmdb=tmdb,
            mdblist=mdblist,
            radarr=radarr,
            sonarr=sonarr,
        )
        self._effects = MemberEffects(sources=self._sources, tmdb=tmdb)
        self._library_gate = library_gate

    async def start(self) -> None:
        """Register a bounded poll; each rule owns its persisted due time."""
        self._scheduler.set_interval_job(
            "collection-rules", enabled=True, func=self.sync_due, minutes=1
        )

    async def stop(self) -> None:
        """Remove polling before the runtime closes its HTTP clients."""
        self._scheduler.remove_job("collection-rules")
        await self._sources.close()

    async def list_radarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Radarr."""
        return await self._sources.radarr_tags()

    async def list_sonarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Sonarr."""
        return await self._sources.sonarr_tags()

    # What the server offers

    def capabilities(self, media_type: MediaType) -> CollectionCapabilities:
        """Describe the fields, sources, orders and sets the server supports."""
        server = self._provider().server_type
        plex = server is ServerType.PLEX
        tmdb = self._app_config.tmdb_configured
        return CollectionCapabilities(
            server_type=server,
            smart=plex,
            visibility=plex,
            member_labels=plex,
            arr=self._sources.arr(media_type).configured,
            charts=[
                chart
                for chart in TmdbChart
                if tmdb and chart_available(media_type, chart)
            ],
            orders=available_orders(server, media_type, smart=False),
            smart_orders=available_orders(server, media_type, smart=True)
            if plex
            else [],
            fields=sorted(
                (
                    CollectionFieldRead(
                        field=field,
                        label=field_label(field, server),
                        kind=spec.kind,
                        operators=list(OPERATORS[spec.kind]),
                        local=local,
                        smart=smart,
                    )
                    for field, spec in FIELDS.items()
                    if (
                        local := field_available(field, server, media_type, smart=False)
                        and (tmdb or not spec.tmdb)
                    )
                    | (smart := field_available(field, server, media_type, smart=True))
                ),
                key=_by_label,
            ),
            sources=sorted(
                (
                    CollectionSourceRead(
                        type=source,
                        label=label,
                        unavailable=self._sources.unavailable(source, media_type),
                    )
                    for source, label in SOURCE_LABELS.items()
                ),
                key=_by_label,
            ),
            dimensions=sorted(
                (
                    CollectionDimensionRead(
                        dimension=dimension,
                        label=spec.label,
                        title_format=spec.title_format,
                        smart_only=smart_only_dimension(dimension, server, media_type),
                    )
                    for dimension, spec in DIMENSIONS.items()
                    if dimension_available(dimension, server, media_type, smart=plex)
                    and (
                        tmdb
                        or (
                            dimension is not SetDimension.FRANCHISE
                            and (spec.field is None or not FIELDS[spec.field].tmdb)
                        )
                    )
                ),
                key=_by_label,
            ),
        )

    async def presets(self, media_type: MediaType) -> list[CollectionPresetRead]:
        """Saved presets, then the built-in ones the server can evaluate."""
        async with self._database.read_session() as session:
            saved = await CollectionRepository(session).presets(media_type)
        return [
            *(saved_preset_read(row) for row in saved),
            *available_presets(
                self._provider().server_type,
                media_type,
                tmdb=self._app_config.tmdb_configured,
            ),
        ]

    async def field_values(
        self, media_type: MediaType, library_id: str, field: FilterField
    ) -> list[CollectionFieldValue]:
        """List a field's values in a library, alphabetically.

        Overture counts what sync stored; fields only Plex knows are listed by
        Plex, without counts.
        """
        server = self._provider().server_type
        if field_available(field, server, media_type, smart=False):
            items = await self._library_items(library_id, media_type)
            collections = (
                await self._collection_titles(media_type, library_id)
                if field is FilterField.COLLECTION
                else {}
            )
            counts: Counter[str] = Counter()
            for item in items:
                value = field_value(item, field, collections.get(item.id or 0, ()))
                if isinstance(value, str):
                    counts[value] += 1
                elif isinstance(value, list | tuple):
                    counts.update({str(entry) for entry in value})
            return [
                CollectionFieldValue(value=value, count=count)
                for value, count in sorted(
                    counts.items(), key=lambda pair: pair[0].casefold()
                )
            ]
        plex = FIELDS[field].plex
        if not field_available(field, server, media_type, smart=True) or plex is None:
            raise PublicServiceError(422, "The media server cannot list this field")
        titles = {
            title
            for _, title in await self._provider().filter_choices(
                library_id, media_type, plex.key_for(media_type)
            )
        }
        return [
            CollectionFieldValue(value=title, count=0)
            for title in sorted(titles, key=str.casefold)
        ]

    # Validation shared by every write

    def _validate_display(
        self,
        options: CollectionOptions | CollectionPolicyBase | CollectionMembersUpdate,
        media_type: MediaType,
        *,
        smart: bool,
    ) -> None:
        server = self._provider().server_type
        if (
            not isinstance(options, CollectionMembersUpdate)
            and server is not ServerType.PLEX
            and (
                options.collection_mode not in {None, CollectionMode.DEFAULT}
                or options.visible_home
                or options.visible_shared
                or options.visible_library
                or options.collection_filtering is not None
            )
        ):
            raise PublicServiceError(422, "Visibility and home promotion require Plex")
        if options.order_type is not None and options.order_type not in (
            available_orders(server, media_type, smart=smart)
        ):
            raise PublicServiceError(
                422,
                SMART_CUSTOM_ORDER
                if smart and options.order_type is CollectionOrder.CUSTOM
                else "The media server cannot order collections this way",
            )

    def _validate_criteria(
        self, media_type: MediaType, criteria: FilterGroup, *, smart: bool
    ) -> None:
        server = self._provider().server_type
        if smart and server is not ServerType.PLEX:
            raise PublicServiceError(
                422, "Smart collections are only supported by Plex"
            )
        for condition in criteria.field_conditions():
            if not field_available(condition.field, server, media_type, smart=smart):
                label = field_label(condition.field, server)
                raise PublicServiceError(
                    422,
                    f"{label} is only available in Plex smart collections"
                    if field_available(condition.field, server, media_type, smart=True)
                    else f"{label} is not available for this library",
                )
            plex = FIELDS[condition.field].plex
            if (
                smart
                and condition.operator is FilterOperator.IS_NOT
                and plex is not None
                and not plex.negatable
            ):
                raise PublicServiceError(
                    422,
                    f"Plex smart collections cannot test that "
                    f"{field_label(condition.field, server)} is not a value",
                )
        for condition in criteria.source_conditions():
            self._sources.require(condition.source.type, media_type)
            if isinstance(condition.source, TmdbChartSource) and not chart_available(
                media_type, condition.source.chart
            ):
                raise PublicServiceError(
                    422, "TMDB has no such chart for this library's titles"
                )

    def _validate_rule(
        self, media_type: MediaType, rule: CollectionRuleWrite, policy: CollectionPolicy
    ) -> None:
        self._validate_criteria(media_type, rule.criteria, smart=rule.smart)
        self._validate_display(
            rule.model_copy(update={"order_type": policy.order_type}),
            media_type,
            smart=rule.smart,
        )

    # Membership

    async def _collection_titles(
        self, media_type: MediaType, library_id: str
    ) -> dict[int, list[str]]:
        async with self._database.read_session() as session:
            return await CollectionRepository(session).titles_by_item(
                media_type, library_id
            )

    async def _context(
        self,
        media_type: MediaType,
        library_id: str,
        criteria: FilterGroup,
        items: list[MediaItem],
    ) -> tuple[CriteriaContext, dict[str, list[int]]]:
        """Resolve each source once, and the collections the criteria test."""
        resolved: dict[str, list[int]] = {}
        for condition in criteria.source_conditions():
            if condition.key not in resolved:
                resolved[condition.key] = await self._sources.resolve(
                    condition.source, media_type, items, region=await self._region()
                )
        collections = (
            await self._collection_titles(media_type, library_id)
            if any(
                condition.field is FilterField.COLLECTION
                for condition in criteria.field_conditions()
            )
            else {}
        )
        context = CriteriaContext(
            sources={key: frozenset(ids) for key, ids in resolved.items()},
            collections=collections,
            now=utc_now(),
        )
        return context, resolved

    async def _region(self) -> str:
        """The region TMDB charts and streaming services are read for."""
        async with self._database.read_session() as session:
            return (await get_app_settings(session)).tmdb_region

    async def _wanted(
        self,
        media_type: MediaType,
        library_id: str,
        criteria: FilterGroup,
        items: list[MediaItem],
        *,
        order: CollectionOrder,
        limit: int | None,
    ) -> list[MediaItem]:
        """The members criteria select, ordered, up to the limit.

        A custom order follows the first source the criteria include.
        """
        context, resolved = await self._context(media_type, library_id, criteria, items)
        source_order = next(
            (
                resolved[condition.key]
                for condition in criteria.source_conditions()
                if condition.operator is FilterOperator.IS
            ),
            list[int](),
        )
        return order_items(
            evaluate(items, criteria, context),
            order,
            source_order=source_order,
            limit=limit,
        )

    async def _sync_label(
        self,
        library_id: str,
        media_type: MediaType,
        label: str,
        wanted_ids: set[int],
        items: list[MediaItem],
    ) -> None:
        """Put the label on exactly the wanted items, on Plex and locally."""
        folded = label.casefold()
        labeled = {
            item.id or 0
            for item in items
            if any(existing.casefold() == folded for existing in item.labels)
        }
        by_id = {item.id or 0: item for item in items}
        add = {
            server_id: by_id[i].labels
            for i in wanted_ids - labeled
            if i in by_id and (server_id := by_id[i].server_item_id)
        }
        remove = sorted(
            server_id
            for i in labeled - wanted_ids
            if (server_id := by_id[i].server_item_id)
        )
        if not add and not remove:
            return
        await self._provider().sync_item_labels(
            library_id, media_type, label, add=add, remove_ids=remove
        )
        async with self._database.write_session() as session:
            for item in await CollectionRepository(session).library_items(
                media_type, library_id
            ):
                kept = [entry for entry in item.labels if entry.casefold() != folded]
                labels = [*kept, label] if (item.id or 0) in wanted_ids else kept
                if labels != item.labels:
                    item.labels = labels
                    session.add(item)

    async def _prune_source_labels(
        self, library_id: str, media_type: MediaType
    ) -> None:
        """Remove source labels no smart collection in the library filters on."""
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            rows = {
                row.id: row
                for row in await repo.list_all()
                if row.library_id == library_id and row.media_type is media_type
            }
            used = {
                source_label(condition)
                for rule in await repo.rules()
                if rule.smart and rule.collection_id in rows
                for condition in _criteria(rule).source_conditions()
            }
            items = await repo.library_items(media_type, library_id)
        stale = {
            label
            for item in items
            for label in item.labels
            if label.startswith(SOURCE_LABEL_PREFIX) and label not in used
        }
        for label in sorted(stale):
            await self._sync_label(library_id, media_type, label, set(), items)

    async def _smart_query(
        self,
        row: MediaCollection,
        rule: CollectionRuleWrite,
        order: CollectionOrder,
        items: list[MediaItem],
    ) -> str:
        """Label each source's items, then compile the query Plex evaluates."""
        library_id = row.library_id or ""
        labels: dict[str, str] = {}
        if sources := rule.criteria.source_conditions():
            _, resolved = await self._context(
                row.media_type, library_id, rule.criteria, items
            )
            for condition in sources:
                labels[condition.key] = source_label(condition)
            for key, label in labels.items():
                await self._sync_label(
                    library_id, row.media_type, label, set(resolved[key]), items
                )
        choices = {
            key: choice_keys(
                await self._provider().filter_choices(library_id, row.media_type, key)
            )
            for key in tag_keys(rule.criteria, row.media_type)
        }
        return compile_plex_query(
            rule.criteria,
            media_type=row.media_type,
            order=order,
            limit=rule.limit,
            choices=choices,
            labels=labels,
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

    @staticmethod
    def _display_order(
        items: list[MediaItem], order: CollectionOrder
    ) -> list[MediaItem]:
        """Show members as the server orders them; stored order is the custom one."""
        if order in {CollectionOrder.CUSTOM, CollectionOrder.RANDOM}:
            return items
        return order_items(items, order)

    async def _push_options(
        self,
        row: MediaCollection,
        options: CollectionOptions,
        rule: RuleOrPolicy = None,
        *,
        push: bool = True,
        source_summary: str | None = None,
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
        summary = self._inherited_summary(
            summary_options,
            policy,
            rule.source_summary if isinstance(rule, CollectionRule) else source_summary,
        )
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
            if row.kind is CollectionKind.SMART
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
        if row.server_item_id is None or not push:
            return effective
        await self._provider().update_collection_details(
            row.server_item_id,
            title=options.title,
            summary=summary,
            sort_title=sort_title,
            mode=options.collection_mode or policy.collection_mode,
            order=order,
            smart=row.kind is CollectionKind.SMART,
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
        options: CollectionOptions,
        policy: CollectionPolicy,
        source_summary: str | None,
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
                source_summary=source_summary,
            )
        except ValueError as exc:
            raise PublicServiceError(422, str(exc)) from exc

    async def create(
        self,
        body: CollectionCreate,
        *,
        generated_value: str | None = None,
        sync: bool = True,
    ) -> CollectionDetail:
        """Create on the server, then record its complete local membership.

        *generated_value* marks a collection its group's set creates. Without
        *sync* the collection is saved in Overture only, until it is synced.
        """
        overrides = body.model_dump(include=body.model_fields_set & _DISPLAY_OVERRIDES)
        body = body.model_copy(update={"rule": body.rule.model_copy(update=overrides)})
        rule = body.rule
        smart = rule.smart
        self._validate_display(body, body.media_type, smart=smart)
        body = body.model_copy(
            update={"collection_group": collection_group(body.collection_group)}
        )
        if (
            body.tmdb_collection_id is not None
            and body.media_type is not MediaType.MOVIE
        ):
            raise PublicServiceError(422, "TMDB collections hold movies only")
        library_items = await self._library_items(body.library_id, body.media_type)
        async with self._database.read_session() as session:
            policy = await self._policy(
                session, body.media_type, body.collection_group, rule
            )
        self._validate_rule(body.media_type, rule, policy)
        if "order_type" not in body.model_fields_set:
            body = body.model_copy(update={"order_type": policy.order_type})
        items = await self._initial_members(body, library_items)
        source_summary = await self._sources.summary(rule.criteria)
        if sync and not smart and len(items) < policy.minimum_items:
            raise PublicServiceError(
                422, "Collection has fewer members than the effective minimum"
            )
        withhold = policy.delete_when_inactive and not self._active(
            body.active_start_mmdd or policy.active_start_mmdd,
            body.active_end_mmdd or policy.active_end_mmdd,
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
                raise PublicServiceError(409, _TITLE_TAKEN)
            now = utc_now()
            row = MediaCollection(
                server_type=self._provider().server_type,
                media_type=body.media_type,
                library_id=body.library_id,
                kind=CollectionKind.SMART if smart else CollectionKind.REGULAR,
                generated_value=generated_value,
                unsynced=not sync,
                last_synced_at=now,
                created_at=now,
                updated_at=now,
                **body.model_dump(exclude={"media_type", "library_id", "rule"}),
            )
            if sync and not withhold:
                items = await self._create_on_server(row, body, items, library_items)
            await self._configure_new(
                row, body, rule, items, smart=smart, source_summary=source_summary
            )
            async with self._database.write_session() as session:
                if row.tmdb_collection_id is None:
                    row.tmdb_collection_id = min(
                        _franchise_ids(rule.criteria), default=None
                    )
                session.add(row)
                await session.flush()
                await CollectionRepository(session).replace_members(
                    row.id or 0, [item.id or 0 for item in items]
                )
                saved_rule = _rule_row(row.id or 0, rule)
                saved_rule.source_summary = source_summary
                session.add(saved_rule)
        await self._publisher.broadcast("collections.changed")
        return await self.get_collection(row.id or 0, body.media_type)

    async def _configure_new(
        self,
        row: MediaCollection,
        body: CollectionCreate,
        rule: CollectionRuleWrite,
        items: list[MediaItem],
        *,
        smart: bool,
        source_summary: str | None,
    ) -> None:
        """Apply display options and order to a new collection, or remove it."""
        try:
            row.child_count = len(items)
            row.summary_source = body.summary
            effective = await self._push_options(
                row, body, rule, source_summary=source_summary
            )
            row.sqlmodel_update(effective.model_dump())
            if not smart and row.server_item_id is not None and items:
                await self._provider().set_collection_members(
                    row.server_item_id,
                    [item.server_item_id for item in items if item.server_item_id],
                    order=body.order_type,
                )
        except Exception:
            # Overture records nothing, so the server keeps no half-made copy.
            if row.server_item_id is not None:
                with suppress(MediaServerError):
                    await self._provider().delete_collection(row.server_item_id)
            raise

    async def _initial_members(
        self,
        body: CollectionCreate,
        library_items: list[MediaItem],
    ) -> list[MediaItem]:
        """What the criteria select; Plex fills a smart collection itself."""
        if body.rule.smart:
            return []
        return await self._wanted(
            body.media_type,
            body.library_id,
            body.rule.criteria,
            library_items,
            order=body.order_type,
            limit=body.rule.limit,
        )

    async def _create_on_server(
        self,
        row: MediaCollection,
        body: CollectionCreate,
        items: list[MediaItem],
        library_items: list[MediaItem],
    ) -> list[MediaItem]:
        """Create the server's collection; Plex decides a smart one's members."""
        if body.rule.smart:
            query = await self._smart_query(
                row, body.rule, body.order_type, library_items
            )
            server = await self._provider().create_smart_collection(
                body.library_id, body.title, body.media_type, query
            )
            by_server_id = {
                item.server_item_id: item
                for item in library_items
                if item.server_item_id
            }
            items = [
                by_server_id[identity]
                for identity in server.member_ids
                if identity in by_server_id
            ]
        else:
            server = await self._provider().create_collection(
                body.library_id,
                body.title,
                body.media_type,
                [item.server_item_id for item in items if item.server_item_id],
            )
        row.sqlmodel_update(
            {
                "server_item_id": server.id,
                "server_link": server.server_link,
                "server_path": server.path,
            }
        )
        return items

    def _active(self, start: str | None, end: str | None) -> bool:
        today = datetime.now(self._app_config.tzinfo).date()
        return is_within_active_window(start, end, today)

    async def update(
        self,
        collection_id: int,
        media_type: MediaType,
        body: CollectionOptions,
        *,
        sync: bool = True,
    ) -> CollectionDetail:
        """Edit collection metadata without touching movie or show metadata."""
        if body.tmdb_collection_id is not None and media_type is not MediaType.MOVIE:
            raise PublicServiceError(422, "TMDB collections hold movies only")
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require_managed(session, collection_id, media_type)
            if row.generated_value is not None and body.title != row.title:
                raise PublicServiceError(
                    422, "Its collection set titles this collection; edit the set"
                )
            await self._update_locked(row, body, push=sync)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        return await self.get_collection(collection_id, media_type)

    async def _update_locked(
        self, row: MediaCollection, body: CollectionOptions, *, push: bool = True
    ) -> None:
        """Persist display choices after the caller acquires the collection locks."""
        overrides: dict[str, object] = {}
        if body.sort_title is not None and body.sort_title_format is None:
            overrides["sort_title_format"] = literal_template(body.sort_title)
        if body.summary is not None and body.summary_format is None:
            overrides["summary_format"] = literal_template(body.summary)
        body = body.model_copy(update=overrides)
        self._validate_display(
            body, row.media_type, smart=row.kind is CollectionKind.SMART
        )
        if body.summary is not None:
            row.summary_source = body.summary
        display = body.model_dump(include=body.model_fields_set & _DISPLAY_OVERRIDES)
        async with self._database.read_session() as session:
            rule = await CollectionRepository(session).rule(row.id or 0)
        if rule is not None:
            body = body.model_copy(
                update={"collection_group": collection_group(body.collection_group)}
            )
            rule.sqlmodel_update(display)
        effective = await self._push_options(row, body, rule, push=push)
        summary_source = row.summary_source
        async with self._database.write_session() as session:
            saved = await self._require(session, row.id or 0, row.media_type)
            fields = effective.model_dump()
            fields["summary_source"] = summary_source
            if "tmdb_collection_id" not in body.model_fields_set:
                fields.pop("tmdb_collection_id")
            saved.sqlmodel_update(fields)
            saved.updated_at = utc_now()
            if not push:
                saved.unsynced = _outdates_server(saved)
            session.add(saved)
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
        if row.kind is CollectionKind.SMART and row.library_id:
            await self._prune_source_labels(row.library_id, row.media_type)
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

    async def delete(
        self,
        collection_id: int,
        media_type: MediaType,
        *,
        target: CollectionDeleteTarget = "both",
    ) -> StatusResponse:
        """Delete a collection and cancel its assets, preserving all media."""
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require_managed(session, collection_id, media_type)
            if target == "server":
                await self._withhold_locked(row)
            else:
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
        """Make the ordered items a regular collection's members on the server."""
        server_item_ids = [item.server_item_id for item in items if item.server_item_id]
        if row.server_item_id is None:
            server = await self._provider().create_collection(
                row.library_id or "", row.title, row.media_type, server_item_ids
            )
            row.server_item_id = server.id
            row.server_link = server.server_link
            row.server_path = server.path
        server_ids = await self._provider().set_collection_members(
            row.server_item_id, server_item_ids, order=order, append=append
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
            current.kind = CollectionKind.REGULAR
            current.child_count = len(server_ids)
            current.order_type = order
            current.updated_at = utc_now()
            session.add(current)
        row.kind = CollectionKind.REGULAR
        await self._publisher.broadcast("collection.updated", {"collection_id": row.id})

    async def set_members(
        self,
        collection_id: int,
        media_type: MediaType,
        body: CollectionMembersUpdate,
        *,
        sync: bool = True,
    ) -> CollectionDetail:
        """Replace members, in an order the server supports."""
        self._validate_display(body, media_type, smart=False)
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require_managed(session, collection_id, media_type)
            if row.kind is CollectionKind.SMART:
                raise PublicServiceError(
                    422, "Smart collection members are controlled by their criteria"
                )
            items = order_items(
                self._resolve_members(
                    body.member_ids,
                    await self._library_items(row.library_id or "", media_type),
                ),
                body.order_type,
            )
            if sync:
                await self._push_options(
                    row,
                    self._saved_options(row, None).model_copy(
                        update={"order_type": body.order_type}
                    ),
                )
                await self._set_members_locked(row, items, body.order_type)
            else:
                await self._store_members(row, items, body.order_type)
        return await self.get_collection(collection_id, media_type)

    async def _store_members(
        self, row: MediaCollection, items: list[MediaItem], order: CollectionOrder
    ) -> None:
        """Save members in Overture only; the next sync sends them."""
        async with self._database.write_session() as session:
            current = await self._require(session, row.id or 0, row.media_type)
            await CollectionRepository(session).replace_members(
                row.id or 0, [item.id or 0 for item in items]
            )
            current.child_count = len(items)
            current.order_type = order
            current.unsynced = _outdates_server(current)
            current.updated_at = utc_now()
            session.add(current)
        await self._publisher.broadcast("collection.updated", {"collection_id": row.id})

    async def save_rule(
        self, collection_id: int, media_type: MediaType, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        """Persist validated criteria; the next sync applies them."""
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.read_session() as session:
                row = await self._require_managed(session, collection_id, media_type)
            if row.generated_value is not None:
                raise PublicServiceError(
                    422,
                    "Its group's collection set decides its criteria; edit the set",
                )
            return await self._save_rule_locked(row, body)

    async def _save_rule_locked(
        self, row: MediaCollection, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        collection_id = row.id or 0
        async with self._database.read_session() as session:
            existing = await CollectionRepository(session).rule(collection_id)
            policy = await self._policy(
                session, row.media_type, row.collection_group, body
            )
        self._validate_rule(row.media_type, body, policy)
        # A new rule keeps the order of a list it selects from, where it can.
        keep_source_order = (
            existing is None
            and body.order_type is None
            and CollectionOrder.CUSTOM
            in available_orders(
                self._provider().server_type, row.media_type, smart=body.smart
            )
            and any(
                condition.source.type in _ORDERED_SOURCES
                for condition in body.criteria.source_conditions()
            )
        )
        if keep_source_order:
            body = body.model_copy(update={"order_type": CollectionOrder.CUSTOM})
            await self._push_options(
                row,
                self._saved_options(row, None).model_copy(
                    update={"order_type": CollectionOrder.CUSTOM}
                ),
                body,
            )
        franchise = min(_franchise_ids(body.criteria), default=None)
        async with self._database.write_session() as session:
            saved_row = await self._require(session, collection_id, row.media_type)
            rule = await CollectionRepository(session).rule(collection_id)
            new_rule = _rule_row(collection_id, body)
            if rule is None:
                rule = new_rule
            else:
                rule.sqlmodel_update(
                    new_rule.model_dump(exclude={"id", "collection_id"})
                )
            rule.last_error = None
            rule.last_synced_at = None
            session.add(rule)
            if keep_source_order:
                saved_row.order_type = CollectionOrder.CUSTOM
            if franchise is not None:
                saved_row.tmdb_collection_id = franchise
            session.add(saved_row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        result = _rule_read(rule)
        if result is None:
            raise RuntimeError("A saved rule must exist")
        return result

    async def _replace_kind(self, row: MediaCollection, *, smart: bool) -> None:
        """Plex cannot convert a collection's kind, so the server copy is replaced."""
        if (
            row.server_item_id is not None
            and (row.kind is CollectionKind.SMART) != smart
        ):
            await self._delete_server_collection(row)
            row.server_item_id = None

    async def _sync_smart_rule_locked(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        body = _rule_read(rule)
        if body is None:
            raise RuntimeError("A smart sync needs its rule")
        await self._replace_kind(row, smart=True)
        query = await self._smart_query(row, body, policy.order_type, library_items)
        if row.server_item_id is None:
            server = await self._provider().create_smart_collection(
                row.library_id or "", row.title, row.media_type, query
            )
            row.server_item_id = server.id
            row.server_link = server.server_link
        else:
            await self._provider().update_smart_collection_filter(
                row.server_item_id, row.library_id or "", row.media_type, query
            )
        row.kind = CollectionKind.SMART
        await self._update_locked(row, self._saved_options(row, rule))
        remote_ids = await self._provider().get_collection_member_ids(
            row.server_item_id
        )
        by_server_id = {
            item.server_item_id: item for item in library_items if item.server_item_id
        }
        stored_ids = [
            by_server_id[identity].id or 0
            for identity in remote_ids
            if identity in by_server_id
        ]
        async with self._database.write_session() as session:
            saved = await self._require(session, row.id or 0, row.media_type)
            await CollectionRepository(session).replace_members(row.id or 0, stored_ids)
            saved.server_item_id = row.server_item_id
            saved.server_link = row.server_link
            saved.kind = CollectionKind.SMART
            saved.child_count = len(remote_ids)
            saved.updated_at = utc_now()
            session.add(saved)
        await self._prune_source_labels(row.library_id or "", row.media_type)
        old_ids = {item.id or 0 for item in current}
        return CollectionSyncResponse(
            added=len(set(stored_ids) - old_ids),
            removed=len(old_ids - set(stored_ids)),
        )

    async def _sync_regular_rule_locked(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        was_smart = row.kind is CollectionKind.SMART
        wanted = await self._wanted(
            row.media_type,
            row.library_id or "",
            _criteria(rule),
            library_items,
            order=policy.order_type,
            limit=rule.item_limit,
        )
        append = policy.sync_mode is SyncMode.APPEND and not was_smart
        if append and row.unsynced:
            # Members chosen in Overture since the last sync replace the server's.
            chosen = {item.id for item in wanted}
            wanted += [item for item in current if item.id not in chosen]
            append = False
        member_count = len(wanted)
        if append and row.server_item_id is not None:
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
        await self._replace_kind(row, smart=False)
        await self._set_members_locked(row, wanted, policy.order_type, append=append)
        await self._update_locked(row, self._saved_options(row, rule))
        if was_smart and row.library_id:
            await self._prune_source_labels(row.library_id, row.media_type)
        old = {item.id for item in current}
        new = {item.id for item in wanted}
        return CollectionSyncResponse(
            added=len(new - old),
            removed=len(old - new) if not append else 0,
        )

    async def sync_rule(
        self, collection_id: int, media_type: MediaType, *, scheduled: bool = False
    ) -> CollectionSyncResponse:
        """Resolve every source before changing any server membership."""
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
                raise PublicServiceError(409, UNMANAGED_REFUSAL)
            if scheduled and not self._due(rule.last_synced_at, policy):
                return CollectionSyncResponse(skipped=True)
            await self._refresh_source_summary(rule)
            error = None
            try:
                if not self._active(
                    row.active_start_mmdd or policy.active_start_mmdd,
                    row.active_end_mmdd or policy.active_end_mmdd,
                ):
                    if policy.delete_when_inactive and row.server_item_id is not None:
                        await self._withhold_locked(row)
                        result = CollectionSyncResponse(
                            deleted=True, removed=len(current)
                        )
                    else:
                        result = CollectionSyncResponse(skipped=True)
                elif rule.smart:
                    result = await self._sync_smart_rule_locked(
                        row, rule, policy, current, library_items
                    )
                else:
                    result = await self._sync_regular_rule_locked(
                        row, rule, policy, current, library_items
                    )
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
            # A skipped server copy still lacks the changes; a collection
            # without one is now withheld until it is active or large enough.
            if not result.skipped or row.server_item_id is None:
                await self._mark_synced(collection_id)
        if not result.skipped and not result.deleted:
            await self._after_sync(collection_id, media_type)
        return result

    async def _refresh_source_summary(self, rule: CollectionRule) -> None:
        """Keep the summary of the rule's first list current for templates.

        A lookup that fails keeps the last summary rather than failing the sync.
        """
        try:
            summary = await self._sources.summary(_criteria(rule))
        except Exception as exc:
            logger.debug("Source summary failed: %s", sanitise_error(str(exc)))
            return
        if summary == rule.source_summary:
            return
        rule.source_summary = summary
        async with self._database.write_session() as session:
            saved = await CollectionRepository(session).rule(rule.collection_id)
            if saved is not None:
                saved.source_summary = summary
                session.add(saved)

    async def _mark_synced(self, collection_id: int) -> None:
        async with self._database.write_session() as session:
            current = await CollectionRepository(session).get(collection_id)
            if current is not None and current.unsynced:
                current.unsynced = False
                session.add(current)

    @staticmethod
    def _due(last_synced_at: datetime | None, policy: CollectionPolicy) -> bool:
        """Whether the schedule has come round since the last sync."""
        return policy.sync_enabled and (
            last_synced_at is None
            or utc_now() >= next_run_after(policy.sync_schedule, last_synced_at)
        )

    async def sync_due(self) -> None:
        """Run due sets and rules independently, so one failure stops none."""
        if self._provider_registry.collections is None:
            return
        if (
            self._library_gate is not None
            and self._library_gate.blocker("downloads") is not None
        ):
            return
        server = self._provider().server_type
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            rules = await repo.rules()
            groups = [
                group
                for media_type in MediaType
                for group in await repo.group_policies(server, media_type)
            ]
        for group in groups:
            generator = _generator(group)
            if generator is None:
                continue
            async with self._database.read_session() as session:
                policy = await self._policy(session, group.media_type, group.name)
            # A set runs on its schedule once it has been synced by hand.
            if group.generated_at is None or not self._due(group.generated_at, policy):
                continue
            try:
                await self._run_set(group, generator, CollectionGroupSyncResult())
            except Exception as exc:
                logger.warning(
                    "Collection set %s failed: %s", group.name, sanitise_error(str(exc))
                )
        for rule in rules:
            async with self._database.read_session() as session:
                row = await CollectionRepository(session).get(rule.collection_id)
                if row is None or row.server_type is not server or _never_created(row):
                    continue
                policy = await self._policy(
                    session, row.media_type, row.collection_group, rule
                )
            if not self._due(rule.last_synced_at, policy):
                continue
            try:
                await self.sync_rule(rule.collection_id, row.media_type, scheduled=True)
            except Exception as exc:
                logger.warning(
                    "Collection rule %s failed: %s",
                    rule.collection_id,
                    sanitise_error(str(exc)),
                )

    async def _after_sync(self, collection_id: int, media_type: MediaType) -> None:
        """Run what a sync does beyond membership, each step whatever the others do.

        Members are already synced, so a failed step is recorded on the rule
        and reported rather than undone.
        """
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            row = await self._require(session, collection_id, media_type)
            rule = await repo.rule(collection_id)
            policy = await self._policy(session, media_type, row.collection_group, rule)
            members = await repo.members(collection_id)
            items = await repo.library_items(media_type, row.library_id or "")
            settings = await get_app_settings(session)
        library_id = row.library_id or ""
        plex = self._provider().server_type is ServerType.PLEX
        arr = self._sources.arr(media_type)
        steps: list[tuple[str, Callable[[], Awaitable[object]]]] = [
            ("Automatic assets", lambda: self._auto_assets(collection_id, media_type))
        ]
        if policy.member_label and plex and row.server_item_id is not None:
            label = format_member_tag(
                policy.member_label, title=row.title, group=row.collection_group
            )
            steps.append(
                (
                    "Member label",
                    lambda: self._sync_label(
                        library_id,
                        media_type,
                        label,
                        {member.id or 0 for member in members},
                        items,
                    ),
                )
            )
        if policy.arr_tag and arr.configured:
            tag = format_member_tag(
                policy.arr_tag, title=row.title, group=row.collection_group
            )
            steps.append(
                ("Member tag", lambda: self._effects.tag(media_type, tag, members))
            )
        if policy.request_missing and arr.configured and rule is not None:
            criteria = _criteria(rule)
            steps.append(
                (
                    "Request missing",
                    lambda: self._request(media_type, criteria, items, settings, None),
                )
            )
        if plex and policy.home_order is not None and row.server_item_id is not None:
            steps.append(
                ("Home order", lambda: self._order_home(library_id, media_type))
            )
        failures: list[str] = []
        for name, step in steps:
            try:
                await step()
            except Exception as exc:
                failures.append(f"{name} failed: {sanitise_error(str(exc))}")
        if not failures:
            return
        message = "Members synced; " + "; ".join(failures)
        async with self._database.write_session() as session:
            saved = await CollectionRepository(session).rule(collection_id)
            if saved is not None:
                saved.last_error = message
                session.add(saved)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )
        raise PublicServiceError(502, message)

    async def _request(
        self,
        media_type: MediaType,
        criteria: FilterGroup,
        items: list[MediaItem],
        settings: AppSettings,
        tmdb_ids: list[int] | None,
    ) -> CollectionRequestResult:
        """Request the given titles, or every missing one, from Radarr or Sonarr."""
        if tmdb_ids is None:
            tmdb_ids = await self._effects.missing_ids(
                criteria, media_type, items, region=settings.tmdb_region
            )
        result = await self._effects.request(media_type, tmdb_ids, settings)
        if result.errors and not result.requested:
            raise PublicServiceError(502, "; ".join(result.errors[:3]))
        return result

    async def _order_home(self, library_id: str, media_type: MediaType) -> None:
        """Order the library's promoted collections on Plex's Home by Home order."""
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.library_id == library_id and row.server_item_id is not None
            ]
            rules = {rule.collection_id: rule for rule in await repo.rules()}
            ordered: list[tuple[int, str, str]] = []
            for row in rows:
                policy = await self._policy(
                    session, media_type, row.collection_group, rules.get(row.id or 0)
                )
                if policy.home_order is not None and (
                    row.visible_home or row.visible_shared or row.visible_library
                ):
                    ordered.append(
                        (
                            policy.home_order,
                            row.title.casefold(),
                            row.server_item_id or "",
                        )
                    )
        await self._provider().order_collection_hubs(
            library_id, [server_id for _, _, server_id in sorted(ordered)]
        )

    # Missing titles, previews and presets

    async def missing(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionMissing:
        """Titles the collection's lists hold that its library lacks."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
        if rule is None:
            return CollectionMissing(
                titles=[], requestable=self._sources.arr(media_type).configured
            )
        return await self._effects.missing(
            _criteria(rule),
            media_type,
            await self._library_items(row.library_id or "", media_type),
            region=await self._region(),
        )

    async def request_missing(
        self, collection_id: int, media_type: MediaType, body: CollectionRequest
    ) -> CollectionRequestResult:
        """Ask Radarr or Sonarr for missing titles, or for the chosen ones."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
            settings = await get_app_settings(session)
        if not self._sources.arr(media_type).configured:
            raise PublicServiceError(
                422,
                "Set up Radarr to request movies"
                if media_type is MediaType.MOVIE
                else "Set up Sonarr to request shows",
            )
        return await self._request(
            media_type,
            _criteria(rule) if rule is not None else FilterGroup(),
            await self._library_items(row.library_id or "", media_type),
            settings,
            body.tmdb_ids,
        )

    async def arr_options(self, media_type: MediaType) -> CollectionArrOptions:
        """The root folders and quality profiles Radarr or Sonarr offers."""
        options = await self._sources.arr(media_type).options()
        return CollectionArrOptions(
            root_folders=list(options.root_folders),
            quality_profiles=[
                ArrTagRead(id=profile.id, label=profile.label)
                for profile in options.quality_profiles
            ],
        )

    async def preview(self, body: CollectionPreviewRequest) -> CollectionPreview:
        """What the criteria select now; Plex counts a smart collection's members."""
        rule = body.rule
        self._validate_criteria(body.media_type, rule.criteria, smart=rule.smart)
        async with self._database.read_session() as session:
            policy = await self._policy(session, body.media_type, None, rule)
        items = await self._library_items(body.library_id, body.media_type)
        recommended = recommend_kind(
            rule,
            self.capabilities(body.media_type),
            media_type=body.media_type,
            order=policy.order_type,
        )
        recommendation = (
            None
            if recommended is None
            else KindRecommendation(kind=recommended[0], reason=recommended[1])
        )
        server = self._provider().server_type
        local = all(
            field_available(condition.field, server, body.media_type, smart=False)
            for condition in rule.criteria.field_conditions()
        )
        if rule.smart and not local:
            if rule.criteria.source_conditions():
                raise PublicServiceError(
                    422, "Save the collection to preview Plex filters with lists"
                )
            total, ids = await self._provider().find_matching(
                body.library_id,
                body.media_type,
                await self._plex_filter(
                    body.library_id, body.media_type, rule.criteria
                ),
                20,
            )
            by_server_id = {item.server_item_id: item.title for item in items}
            return CollectionPreview(
                member_count=min(total, rule.limit or total),
                members=[by_server_id[i] for i in ids if i in by_server_id],
                recommendation=recommendation,
            )
        wanted = await self._wanted(
            body.media_type,
            body.library_id,
            rule.criteria,
            items,
            order=policy.order_type,
            limit=rule.limit,
        )
        return CollectionPreview(
            member_count=len(wanted),
            members=[item.title for item in wanted[:20]],
            recommendation=recommendation,
        )

    async def save_preset(self, body: CollectionPresetSave) -> CollectionPresetRead:
        """Keep a collection or set as a preset, replacing one of the same name."""
        async with self._database.write_session() as session:
            existing = next(
                (
                    row
                    for row in await CollectionRepository(session).presets(
                        body.media_type
                    )
                    if row.label.casefold() == body.label.casefold()
                ),
                None,
            )
            row = existing or CollectionPreset(
                media_type=body.media_type, label=body.label, payload_json=""
            )
            row.label = body.label
            row.description = body.description
            row.payload_json = body.model_dump_json()
            row.created_at = row.created_at or utc_now()
            session.add(row)
            await session.flush()
            return saved_preset_read(row)

    async def delete_preset(self, preset_id: int) -> StatusResponse:
        """Forget a saved preset."""
        async with self._database.write_session() as session:
            row = await session.get(CollectionPreset, preset_id)
            if row is None:
                raise PublicServiceError(404, "Preset not found")
            await session.delete(row)
        return StatusResponse(status=Status.DELETED)

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
        # Candidates come from the TMDB franchise, or a person the criteria list.
        if policy.auto_match_art:
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

    # Collection sets

    def _validate_generator(
        self, media_type: MediaType, generator: CollectionGeneratorBase
    ) -> None:
        server = self._provider().server_type
        dimension = DIMENSIONS[generator.dimension]
        if not dimension_available(
            generator.dimension, server, media_type, smart=generator.smart
        ):
            raise PublicServiceError(
                422,
                f"{dimension.label} need a set of Plex smart collections"
                if dimension_available(
                    generator.dimension, server, media_type, smart=True
                )
                else f"{dimension.label} are not available for this library",
            )
        if generator.dimension is SetDimension.FRANCHISE:
            self._sources.require(SourceType.TMDB_COLLECTION, media_type)
        # Overture counts values itself, then Plex may evaluate each collection.
        for criteria in (
            generator.criteria,
            *(value.criteria for value in generator.custom_values),
        ):
            if not smart_only_dimension(generator.dimension, server, media_type):
                self._validate_criteria(media_type, criteria, smart=False)
            if generator.smart:
                self._validate_criteria(media_type, criteria, smart=True)
        if (
            generator.smart
            and dimension.field is not None
            and not field_available(dimension.field, server, media_type, smart=True)
        ):
            raise PublicServiceError(
                422, f"Plex smart collections cannot test {dimension.label}"
            )

    async def _set_values(
        self,
        media_type: MediaType,
        generator: CollectionGeneratorBase,
        library_id: str,
        group: str | None,
        minimum: int,
    ) -> list[tuple[SetValue, bool]]:
        """The set's values in one library, and whether each is below the minimum.

        Franchises below the minimum, or kept by collections outside the group,
        are left out rather than looked up on TMDB. Values only Plex knows are
        counted by Plex.
        """
        self._validate_generator(media_type, generator)
        server = self._provider().server_type
        if smart_only_dimension(generator.dimension, server, media_type):
            counts = await self._plex_counts(media_type, generator, library_id)
        else:
            items = await self._library_items(library_id, media_type)
            context, _ = await self._context(
                media_type,
                library_id,
                FilterGroup(
                    groups=[
                        generator.criteria,
                        *(value.criteria for value in generator.custom_values),
                    ]
                ),
                items,
            )
            counts = count_values(generator, items, context)
        names: dict[str, str] = {}
        if generator.dimension is SetDimension.FRANCHISE:
            elsewhere = await self._franchises_elsewhere(media_type, group)
            for value, count in list(counts.items()):
                name = (
                    await self._sources.franchise_name(int(value))
                    if count >= minimum and int(value) not in elsewhere
                    else None
                )
                if name is None:
                    del counts[value]
                else:
                    names[value] = name
        return [
            (value, value.count < minimum)
            for value in set_values(generator, counts, names)
        ]

    async def _plex_counts(
        self, media_type: MediaType, generator: CollectionGeneratorBase, library_id: str
    ) -> Counter[str]:
        """Count each value of a field only Plex knows, as Plex evaluates it."""
        field = DIMENSIONS[generator.dimension].field
        plex = FIELDS[field].plex if field is not None else None
        if field is None or plex is None:
            raise PublicServiceError(422, "Plex cannot count this dimension")
        provider = self._provider()
        titles = sorted(
            {
                title
                for _, title in await provider.filter_choices(
                    library_id, media_type, plex.key_for(media_type)
                )
            },
            key=str.casefold,
        )
        counts: Counter[str] = Counter()
        for title in titles:
            criteria = FilterGroup(
                conditions=[
                    FieldCondition(field=field, operator=FilterOperator.IS, value=title)
                ],
                groups=[] if generator.criteria.is_empty() else [generator.criteria],
            )
            total, _ = await provider.find_matching(
                library_id,
                media_type,
                await self._plex_filter(library_id, media_type, criteria),
                0,
            )
            counts[title] = total
        return counts

    async def _plex_filter(
        self, library_id: str, media_type: MediaType, criteria: FilterGroup
    ) -> str:
        """Compile criteria without lists into the query Plex evaluates."""
        choices = {
            key: choice_keys(
                await self._provider().filter_choices(library_id, media_type, key)
            )
            for key in tag_keys(criteria, media_type)
        }
        return compile_plex_query(
            criteria,
            media_type=media_type,
            order=CollectionOrder.TITLE_ASC,
            limit=None,
            choices=choices,
            labels={},
        )

    async def _franchises_elsewhere(
        self, media_type: MediaType, group: str | None
    ) -> set[int]:
        """TMDB franchises collections outside the group already hold."""
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            outside = {
                row.id: row
                for row in await repo.list_listed(media_type)
                if row.collection_group != group
                and row.server_type is self._provider().server_type
            }
            rules = await repo.rules()
        return {
            row.tmdb_collection_id
            for row in outside.values()
            if row.tmdb_collection_id is not None
        } | {
            franchise
            for rule in rules
            if rule.collection_id in outside
            for franchise in _franchise_ids(_criteria(rule))
        }

    async def preview_set(self, body: CollectionSetPreview) -> list[CollectionSetEntry]:
        """Preview a set's collections in each library, saving nothing."""
        async with self._database.read_session() as session:
            minimum = (
                body.minimum_items
                or (
                    await self._policy(session, body.media_type, body.group)
                ).minimum_items
            )
            existing = {
                (row.library_id, row.generated_value): row.id
                for row in await CollectionRepository(session).list_listed(
                    body.media_type
                )
                if body.group
                and row.collection_group == body.group
                and row.generated_value is not None
            }
        return [
            CollectionSetEntry(
                library_id=library_id,
                value=value.value,
                title=value.title,
                member_count=value.count,
                below_minimum=below,
                collection_id=existing.get((library_id, value.value)),
            )
            for library_id in body.generator.library_ids
            for value, below in await self._set_values(
                body.media_type, body.generator, library_id, body.group, minimum
            )
        ]

    async def _run_set(
        self,
        group: CollectionGroup,
        generator: CollectionGenerator,
        result: CollectionGroupSyncResult,
    ) -> None:
        """Create the set's new collections, update the rest and remove stale ones.

        Values below the minimum go when the policy deletes them, and so do
        values the library no longer holds or the set no longer selects.
        """
        media_type = group.media_type
        async with self._database.read_session() as session:
            policy = await self._policy(session, media_type, group.name)
            listed = [
                row
                for row in await CollectionRepository(session).list_listed(media_type)
                if row.server_type is self._provider().server_type
            ]
            rules = {
                rule.collection_id: rule
                for rule in await CollectionRepository(session).rules()
            }
        for library_id in generator.library_ids:
            in_library = [row for row in listed if row.library_id == library_id]
            members = {
                row.generated_value: row
                for row in in_library
                if row.collection_group == group.name
                and row.generated_value is not None
            }
            titles = {
                row.title.casefold()
                for row in in_library
                if row.generated_value is None or row.collection_group != group.name
            }
            # A value the set no longer selects has no members, so it is below minimum.
            stale: set[str] = set(members) if policy.delete_below_minimum else set()
            for value, below in await self._set_values(
                media_type, generator, library_id, group.name, policy.minimum_items
            ):
                stale.discard(value.value)
                if below:
                    if policy.delete_below_minimum and value.value in members:
                        stale.add(value.value)
                    continue
                await self._apply_set_value(
                    group, generator, library_id, value, members, titles, rules, result
                )
            for value in sorted(stale):
                row = members[value]
                try:
                    await self.delete(row.id or 0, media_type)
                    result.removed.append(row.id or 0)
                except Exception as exc:
                    result.errors[row.title] = sanitise_error(str(exc))
        async with self._database.write_session() as session:
            saved = await CollectionRepository(session).group_policy(
                group.server_type, media_type, group.name
            )
            if saved is not None:
                saved.generated_at = utc_now()
                session.add(saved)
        await self._publisher.broadcast("collections.changed")

    async def _apply_set_value(
        self,
        group: CollectionGroup,
        generator: CollectionGenerator,
        library_id: str,
        value: SetValue,
        members: Mapping[str, MediaCollection],
        titles: set[str],
        rules: Mapping[int, CollectionRule],
        result: CollectionGroupSyncResult,
    ) -> None:
        """Create the value's collection, or bring the existing one up to date."""
        rule = CollectionRuleWrite(criteria=value.criteria, smart=generator.smart)
        try:
            row = members.get(value.value)
            if row is not None:
                await self._refresh_generated(row, rules.get(row.id or 0), value, rule)
                return
            if value.title.casefold() in titles:
                raise PublicServiceError(409, _TITLE_TAKEN)
            detail = await self.create(
                CollectionCreate(
                    title=value.title,
                    media_type=group.media_type,
                    library_id=library_id,
                    collection_group=group.name,
                    rule=rule,
                ),
                generated_value=value.value,
            )
            result.created.append(detail.id)
            titles.add(value.title.casefold())
            await self._after_sync(detail.id, group.media_type)
        except Exception as exc:
            result.errors[value.title] = sanitise_error(str(exc))

    async def _refresh_generated(
        self,
        row: MediaCollection,
        saved: CollectionRule | None,
        value: SetValue,
        rule: CollectionRuleWrite,
    ) -> None:
        """Bring a set's collection in line with the set's current definition."""
        collection_id = row.id or 0
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            if row.title != value.title:
                await self._update_locked(
                    row,
                    self._saved_options(row, saved).model_copy(
                        update={"title": value.title}
                    ),
                )
            current = _rule_read(saved)
            if (
                current is None
                or current.criteria != rule.criteria
                or current.smart != rule.smart
            ):
                overrides = (
                    current.model_dump(exclude={"criteria", "smart", "limit"})
                    if current
                    else {}
                )
                overrides.pop("last_synced_at", None)
                overrides.pop("last_error", None)
                await self._save_rule_locked(row, rule.model_copy(update=overrides))

    # Groups

    async def rename_group(
        self, media_type: MediaType, name: str, replacement: str
    ) -> StatusResponse:
        """Rename defaults and every member atomically, including unlisted rows."""
        name, replacement = name.strip(), _group_name(replacement)
        if UNGROUPED_GROUP.casefold() in {name.casefold(), replacement.casefold()}:
            raise PublicServiceError(
                422, "The Ungrouped group cannot be renamed or replaced"
            )
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
        """Remove a group only after each selected collection operation succeeds.

        Raises:
            PublicServiceError: 422 for the reserved fallback or a move into itself.
        """
        name = name.strip()
        if name.casefold() == UNGROUPED_GROUP.casefold():
            raise PublicServiceError(422, "The Ungrouped group cannot be deleted")
        target = collection_group(body.group)
        if target.casefold() == name.casefold():
            raise PublicServiceError(422, "Move the collections to another group")
        server = self._provider().server_type
        result = BulkCollectionOperationResult()
        async with self._downloads.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._database.read_session() as session:
                repo = CollectionRepository(session)
                rows = await repo.group_members(server, media_type, name)
                group = await repo.group_policy(server, media_type, name)
            if group is None and not rows:
                raise PublicServiceError(404, "Collection group not found")
            if body.collections in {"overture", "both"}:
                for row in rows:
                    identity = row.id or 0
                    try:
                        async with self._downloads.asset_locks.acquire(
                            f"collection:{identity}"
                        ):
                            await self._delete_locked(
                                row, server=body.collections == "both"
                            )
                        result.collection_ids.append(identity)
                    except Exception as exc:
                        result.errors[identity] = sanitise_error(str(exc))
            else:
                result.collection_ids.extend(row.id or 0 for row in rows)
            if not result.errors:
                async with self._database.write_session() as session:
                    repo = CollectionRepository(session)
                    for row in await repo.group_members(server, media_type, name):
                        row.collection_group = target
                        row.generated_value = None
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
        return CollectionGroupPolicy(
            **row.model_dump(
                include=set(CollectionGroupPolicy.model_fields) - {"generator"}
            ),
            generator=_generator(row),
        )

    async def save_group_policy(
        self, media_type: MediaType, name: str, body: CollectionGroupPolicy
    ) -> CollectionGroupPolicy:
        """Save group defaults without replacing explicit collection overrides."""
        name = _group_name(name)
        self._validate_display(body, media_type, smart=False)
        if body.generator is not None:
            self._validate_generator(media_type, body.generator)
            if body.generator.smart and body.order_type is CollectionOrder.CUSTOM:
                raise PublicServiceError(422, SMART_CUSTOM_ORDER)
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
            row.sqlmodel_update(body.model_dump(exclude={"generator"}))
            row.generator_json = (
                body.generator.model_dump_json() if body.generator is not None else None
            )
            session.add(row)
        await self._publisher.broadcast("collections.changed")
        return body

    async def apply_group_policy(
        self, media_type: MediaType, name: str
    ) -> BulkCollectionOperationResult:
        """Apply display defaults while preserving sources and rule overrides.

        A group may mix regular and smart collections; Plex orders smart ones
        itself, so a custom order skips them.
        """
        server = self._provider().server_type
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            policy = await repo.group_policy(server, media_type, name)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.collection_group == name
                and row.server_type is server
                and row.id is not None
            ]
        result = BulkCollectionOperationResult()
        custom = policy is not None and policy.order_type is CollectionOrder.CUSTOM
        ids: list[int] = []
        for row in rows:
            if custom and row.kind is CollectionKind.SMART:
                result.skipped[row.id or 0] = SMART_CUSTOM_ORDER
            else:
                ids.append(row.id or 0)
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

    async def sync_group(
        self, media_type: MediaType, name: str
    ) -> CollectionGroupSyncResult:
        """Run the group's set, if it is one, then sync its other collections."""
        name = name.strip()
        async with self._database.read_session() as session:
            group = await CollectionRepository(session).group_policy(
                self._provider().server_type, media_type, name
            )
        result = CollectionGroupSyncResult()
        generator = _generator(group)
        if group is not None and generator is not None:
            await self._run_set(group, generator, result)
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.server_type is self._provider().server_type
                and row.collection_group == name
            ]
            managed = {rule.collection_id for rule in await repo.rules()}
        for row in rows:
            if row.id in managed and row.id not in result.created:
                try:
                    await self.sync_rule(row.id or 0, media_type)
                    result.synced += 1
                except Exception as exc:
                    result.errors[row.title] = sanitise_error(str(exc))
        return result

    @staticmethod
    def _saved_options(
        row: MediaCollection, rule: CollectionRule | None
    ) -> CollectionOptions:
        options = CollectionOptions(
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
            options.collection_group = body.collection_group
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
        async with self._database.read_session() as session:
            managed = await CollectionRepository(session).managed_ids(
                body.collection_ids
            )
        for collection_id in body.collection_ids:
            # Take-over is the one change a collection Overture does not manage accepts.
            if (collection_id in managed) == (body.operation == "take_over"):
                result.errors[collection_id] = (
                    "Overture already manages it"
                    if body.operation == "take_over"
                    else UNMANAGED_REFUSAL
                )
                continue
            try:
                if body.operation == "delete":
                    await self.delete(collection_id, body.media_type)
                elif body.operation == "trigger_sync":
                    await self.sync_rule(collection_id, body.media_type)
                elif body.operation in {"clear_artwork", "clear_themes"}:
                    await self._forget_selections(
                        collection_id,
                        body.media_type,
                        artwork=body.operation == "clear_artwork",
                    )
                elif body.operation == "take_over":
                    await self.take_over(
                        collection_id,
                        body.media_type,
                        CollectionTakeOver(group=body.collection_group),
                    )
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

    async def _require_managed(
        self, session: AsyncSession, collection_id: int, media_type: MediaType
    ) -> MediaCollection:
        """Return a listed collection Overture manages; only take-over changes others.

        Raises:
            PublicServiceError: 409 when the collection has not been taken over.
        """
        row = await self._require(session, collection_id, media_type)
        if await CollectionRepository(session).rule(collection_id) is None:
            raise PublicServiceError(409, UNMANAGED_REFUSAL)
        return row

    async def list_collections(self, media_type: MediaType) -> list[CollectionRead]:
        """Return the collections the last sync listed for the media type."""
        server = self._provider().server_type
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.server_type is server
            ]
            defaults = await get_app_settings(session)
            groups = {
                group.name: group
                for group in await repo.group_policies(server, media_type)
            }
            rules = {rule.collection_id: rule for rule in await repo.rules()}
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id for row in rows if row.tmdb_collection_id},
                app_config=self._app_config,
            )
        return [
            collection_read(
                row,
                catalog.get(row.tmdb_collection_id or 0),
                rule,
                trust_no_theme=defaults.overturedb_no_theme,
            ).model_copy(
                update={
                    "below_minimum": row.child_count < policy.minimum_items,
                    "home_order": policy.home_order,
                    "has_incorrect_aspect_ratio": any(
                        has_incorrect_aspect_ratio(
                            slot.width,
                            slot.height,
                            art_type,
                            defaults.aspect_ratio_tolerance,
                        )
                        for art_type in ITEM_ART_TYPES
                        if (slot := find_art_slot(row, art_type)) is not None
                    ),
                }
            )
            for row in rows
            for rule in (rules.get(row.id or 0),)
            for policy in (
                resolve_policy(defaults, groups.get(row.collection_group or ""), rule),
            )
        ]

    async def groups(self, media_type: MediaType) -> list[str]:
        """Return the stored groups: those with defaults or managed collections.

        Unmanaged collections belong to no group until they are taken over.
        """
        provider = self._provider()
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.server_type is provider.server_type
            ]
            policies = await repo.group_policies(provider.server_type, media_type)
            managed = {rule.collection_id for rule in await repo.rules()}
        return sorted(
            {UNGROUPED_GROUP}
            | {group.name for group in policies}
            | {
                row.collection_group
                for row in rows
                if row.collection_group and row.id in managed
            }
        )

    async def _forget_selections(
        self, collection_id: int, media_type: MediaType, *, artwork: bool
    ) -> None:
        """Forget saved art or theme choices; server images and files stay."""
        async with (
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
            self._database.write_session() as session,
        ):
            row = await self._require_managed(session, collection_id, media_type)
            if artwork:
                for art_type in ITEM_ART_TYPES:
                    clear_art_selection(row, art_type)
            else:
                row.youtube_id = None
                row.youtube_id_source = None
                row.youtube_title = None
                row.youtube_duration = None
            row.updated_at = utc_now()
            session.add(row)
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )

    async def take_over(
        self, collection_id: int, media_type: MediaType, body: CollectionTakeOver
    ) -> CollectionDetail:
        """Give a collection made outside Overture a rule that keeps it as it is.

        A regular collection keeps its current members; a Plex smart collection
        keeps its filter, read back into criteria.

        Raises:
            PublicServiceError: 409 when it already has a rule, 422 when its
                Plex filter has terms criteria cannot express.
        """
        async with self._database.read_session() as session:
            repo = CollectionRepository(session)
            row = await self._require(session, collection_id, media_type)
            if await repo.rule(collection_id) is not None:
                raise PublicServiceError(409, "Overture already manages it")
            members = await repo.members(collection_id)
        body = body.model_copy(update={"group": collection_group(body.group)})
        if row.kind is CollectionKind.SMART:
            rule = await self._smart_takeover_rule(row)
        else:
            rule = CollectionRuleWrite(criteria=_member_criteria(row, members))
        async with (
            self._downloads.asset_locks.acquire(COLLECTIONS_LOCK),
            self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            async with self._database.write_session() as session:
                stored = await self._require(session, collection_id, media_type)
                stored.collection_group = body.group
                session.add(stored)
            await self._save_rule_locked(stored, rule)
        return await self.get_collection(collection_id, media_type)

    async def _smart_takeover_rule(self, row: MediaCollection) -> CollectionRuleWrite:
        provider = self._provider()
        if row.server_item_id is None or row.library_id is None:
            raise PublicServiceError(409, "The collection has no server copy")
        query = await provider.smart_collection_filter(row.server_item_id)
        fields = plex_field_keys(row.media_type)
        names: dict[str, dict[str, str]] = {}
        for name, _ in urllib.parse.parse_qsl(query):
            key = name.rstrip("!<>=")
            field = fields.get(key)
            if field is None or key in names or plex_field(field).type != "tag":
                continue
            choices = await provider.filter_choices(row.library_id, row.media_type, key)
            names[key] = dict(choices)
        try:
            decompiled = decompile_plex_query(
                query, media_type=row.media_type, names=names
            )
        except UnmappableFilterError as exc:
            raise PublicServiceError(422, str(exc)) from exc
        return CollectionRuleWrite(
            criteria=decompiled.criteria,
            smart=True,
            order_type=decompiled.order,
            limit=decompiled.limit,
        )

    async def get_collection(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionDetail:
        """Return one collection with its members and catalog entry."""
        async with self._database.read_session() as session:
            row = await self._require(session, collection_id, media_type)
            saved = await CollectionRepository(session).rule(collection_id)
            members = self._display_order(
                await CollectionRepository(session).members(row.id or 0), row.order_type
            )
            policy = await self._policy(
                session, media_type, row.collection_group, saved
            )
            member_reads = await media_item_reads_with_public_dataset_status(
                session, members
            )
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
                app_config=self._app_config,
            )
            trust_no_theme = (await get_app_settings(session)).overturedb_no_theme
        entry = catalog.get(row.tmdb_collection_id or 0)
        reason = await collection_theme_unavailable(
            row, provider=self._provider(), app_config=self._app_config
        )
        return CollectionDetail(
            **collection_read(row, entry, saved, trust_no_theme=trust_no_theme)
            .model_copy(
                update={"below_minimum": row.child_count < policy.minimum_items}
            )
            .model_dump(),
            effective_sync_mode=policy.sync_mode,
            members=member_reads,
            rule=_rule_read(saved),
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
            row = await self._require_managed(session, collection_id, body.media_type)
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
            await self._require_managed(session, collection_id, media_type)
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
            row = await self._require_managed(session, collection_id, media_type)
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
        if (current_url := row.server_image_url(art_type)) is None:
            raise PublicServiceError(404, "Collection image not found")
        request = await provider.build_collection_image_request(
            row.server_item_id, art_type, size, current_url=current_url
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
