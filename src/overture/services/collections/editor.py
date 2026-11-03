"""Changing one collection: creating, editing, membership, rules and removal."""

lazy import urllib.parse
lazy from contextlib import suppress

lazy from ...db.art_slots import clear_art_selection
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import (
    ITEM_ART_TYPES,
    AssetScope,
    CollectionKind,
    CollectionOrder,
    MediaType,
)
lazy from ...media_servers.errors import MediaServerError
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    CollectionAdoption,
    CollectionAdoptionPlan,
    CollectionCreate,
    CollectionDeleteTarget,
    CollectionDetail,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionRuleRead,
    CollectionRuleWrite,
)
lazy from ...schemas.common import (
    BulkMonitorResponse,
    MonitoredResponse,
    Status,
    StatusResponse,
)
lazy from ...utils.collection_formats import literal_template
lazy from ...utils.collection_groups import collection_group
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..downloads.service import DownloadService
lazy from . import COLLECTIONS_LOCK
lazy from .access import CollectionAccess
lazy from .criteria import order_items
lazy from .display import DISPLAY_OVERRIDES, CollectionDisplay, saved_options
lazy from .fields import available_orders
lazy from .membership import Membership, resolve_members, stored_ids
lazy from .plex_query import (
    UnmappableFilterError,
    decompile_plex_query,
    plex_field,
    plex_field_keys,
)
lazy from .reader import CollectionReader
lazy from .rules import (
    ORDERED_SOURCES,
    TITLE_TAKEN,
    franchise_ids,
    member_criteria,
    outdates_server,
    rule_read,
    rule_row,
    shared_franchise,
)
lazy from .rules import criteria as rule_criteria
lazy from .sources import SourceResolver
lazy from .validation import CollectionValidator


class CollectionEditor:
    """Create, edit and remove collections, on the server and in Overture.

    The ``*_locked`` methods expect the caller to hold
    :meth:`CollectionAccess.locked` for the collection.
    """

    def __init__(
        self,
        *,
        access: CollectionAccess,
        validator: CollectionValidator,
        membership: Membership,
        display: CollectionDisplay,
        reader: CollectionReader,
        sources: SourceResolver,
        downloads: DownloadService,
    ) -> None:
        self._access = access
        self._validator = validator
        self._membership = membership
        self._display = display
        self._reader = reader
        self._sources = sources
        self._downloads = downloads

    # Creating

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
        overrides = body.model_dump(include=body.model_fields_set & DISPLAY_OVERRIDES)
        body = body.model_copy(update={"rule": body.rule.model_copy(update=overrides)})
        rule = body.rule
        smart = rule.smart
        self._validator.display(body, body.media_type, smart=smart)
        body = body.model_copy(
            update={"collection_group": collection_group(body.collection_group)}
        )
        if (
            body.tmdb_collection_id is not None
            and body.media_type is not MediaType.MOVIE
        ):
            raise PublicServiceError(422, "TMDB collections hold movies only")
        library_items = await self._access.library_items(
            body.library_id, body.media_type
        )
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(
                session, body.media_type, body.collection_group, rule
            )
        self._validator.rule(body.media_type, rule, policy)
        if "order_type" not in body.model_fields_set:
            body = body.model_copy(update={"order_type": policy.order_type})
        items = await self._initial_members(body, library_items)
        source_summary = await self._sources.summary(rule.criteria)
        if sync and not smart and len(items) < policy.minimum_items:
            raise PublicServiceError(
                422, "Collection has fewer members than the effective minimum"
            )
        withhold = policy.delete_when_inactive and not self._access.active(
            body.active_start_mmdd or policy.active_start_mmdd,
            body.active_end_mmdd or policy.active_end_mmdd,
        )
        server = self._access.server_type
        async with self._access.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._access.database.read_session() as session:
                existing = await CollectionRepository(session).list_listed(
                    body.media_type
                )
            if any(
                row.library_id == body.library_id
                and row.title.casefold() == body.title.casefold()
                and row.server_type is server
                for row in existing
            ):
                raise PublicServiceError(409, TITLE_TAKEN)
            now = utc_now()
            row = MediaCollection(
                server_type=server,
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
            async with self._access.database.write_session() as session:
                if row.tmdb_collection_id is None:
                    row.tmdb_collection_id = min(
                        franchise_ids(rule.criteria), default=None
                    )
                session.add(row)
                await session.flush()
                await CollectionRepository(session).replace_members(
                    row.id or 0, [item.id or 0 for item in items]
                )
                saved_rule = rule_row(row.id or 0, rule)
                saved_rule.source_summary = source_summary
                session.add(saved_rule)
        await self._access.changed()
        return await self._reader.get(row.id or 0, body.media_type)

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
        provider = self._access.provider()
        try:
            row.child_count = len(items)
            row.summary_source = body.summary
            effective = await self._display.push(
                row, body, rule, source_summary=source_summary
            )
            row.sqlmodel_update(effective.model_dump())
            if not smart and row.server_item_id is not None and items:
                await provider.set_collection_members(
                    row.server_item_id,
                    [item.server_item_id for item in items if item.server_item_id],
                    order=body.order_type,
                )
        except Exception:
            # Overture records nothing, so the server keeps no half-made copy.
            if row.server_item_id is not None:
                with suppress(MediaServerError):
                    await provider.delete_collection(row.server_item_id)
            raise

    async def _initial_members(
        self, body: CollectionCreate, library_items: list[MediaItem]
    ) -> list[MediaItem]:
        """What the criteria select; Plex fills a smart collection itself."""
        if body.rule.smart:
            return []
        return await self._membership.wanted(
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
        provider = self._access.provider()
        if body.rule.smart:
            query = await self._membership.smart_query(
                row, body.rule, body.order_type, library_items
            )
            server = await provider.create_smart_collection(
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
            server = await provider.create_collection(
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

    # Display options

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
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(
                    session, collection_id, media_type
                )
            if row.generated_value is not None and body.title != row.title:
                raise PublicServiceError(
                    422, "Its collection set titles this collection; edit the set"
                )
            await self.update_locked(row, body, push=sync)
        await self._access.updated(collection_id)
        return await self._reader.get(collection_id, media_type)

    async def update_locked(
        self, row: MediaCollection, body: CollectionOptions, *, push: bool = True
    ) -> None:
        """Persist display choices after the caller acquires the collection locks."""
        overrides: dict[str, object] = {}
        if body.sort_title is not None and body.sort_title_format is None:
            overrides["sort_title_format"] = literal_template(body.sort_title)
        if body.summary is not None and body.summary_format is None:
            overrides["summary_format"] = literal_template(body.summary)
        body = body.model_copy(update=overrides)
        self._validator.display(
            body, row.media_type, smart=row.kind is CollectionKind.SMART
        )
        if body.summary is not None:
            row.summary_source = body.summary
        display = body.model_dump(include=body.model_fields_set & DISPLAY_OVERRIDES)
        async with self._access.database.read_session() as session:
            rule = await CollectionRepository(session).rule(row.id or 0)
        if rule is not None:
            body = body.model_copy(
                update={"collection_group": collection_group(body.collection_group)}
            )
            rule.sqlmodel_update(display)
        effective = await self._display.push(row, body, rule, push=push)
        summary_source = row.summary_source
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0, row.media_type)
            fields = effective.model_dump()
            fields["summary_source"] = summary_source
            if "tmdb_collection_id" not in body.model_fields_set:
                fields.pop("tmdb_collection_id")
            saved.sqlmodel_update(fields)
            saved.updated_at = utc_now()
            if not push:
                saved.unsynced = outdates_server(saved)
            session.add(saved)
            if rule is not None and display:
                saved_rule = await CollectionRepository(session).rule(row.id or 0)
                if saved_rule is not None:
                    saved_rule.sqlmodel_update(display)
                    session.add(saved_rule)

    # Removing

    async def delete_server_collection(self, row: MediaCollection) -> None:
        """A server-side deletion is complete when the collection is already absent."""
        if row.server_item_id is not None:
            try:
                await self._access.provider().delete_collection(row.server_item_id)
            except MediaServerError as exc:
                if exc.upstream_status_code != 404:
                    raise

    async def delete_locked(self, row: MediaCollection, *, server: bool = True) -> None:
        collection_id = row.id or 0
        if server:
            await self.delete_server_collection(row)
        async with self._access.database.write_session() as session:
            await self._downloads.cancel_assets(
                session, AssetScope(collection_id=collection_id)
            )
            await CollectionRepository(session).delete_ids([collection_id])
        await self._downloads.committed(session)
        if row.kind is CollectionKind.SMART and row.library_id:
            await self._membership.prune_source_labels(row.library_id, row.media_type)
        await self._access.changed()

    async def withhold_locked(self, row: MediaCollection) -> None:
        """Remove a collection from the server while keeping its Overture rule."""
        collection_id = row.id or 0
        await self.delete_server_collection(row)
        async with self._access.database.write_session() as session:
            current = await CollectionRepository(session).get(collection_id)
            if current is not None:
                current.server_item_id = None
                current.child_count = 0
                current.updated_at = utc_now()
                session.add(current)
            await CollectionRepository(session).replace_members(collection_id, [])
        await self._access.changed()

    async def delete(
        self,
        collection_id: int,
        media_type: MediaType,
        *,
        target: CollectionDeleteTarget = "both",
    ) -> StatusResponse:
        """Delete a collection and cancel its assets, preserving all media."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(
                    session, collection_id, media_type
                )
            if target == "server":
                await self.withhold_locked(row)
            else:
                await self.delete_locked(row)
        return StatusResponse(status=Status.DELETED)

    # Members

    async def set_members_locked(
        self,
        row: MediaCollection,
        items: list[MediaItem],
        order: CollectionOrder,
        *,
        append: bool = False,
    ) -> None:
        """Make the ordered items a regular collection's members on the server."""
        provider = self._access.provider()
        server_item_ids = [item.server_item_id for item in items if item.server_item_id]
        if row.server_item_id is None:
            server = await provider.create_collection(
                row.library_id or "", row.title, row.media_type, server_item_ids
            )
            row.server_item_id = server.id
            row.server_link = server.server_link
            row.server_path = server.path
        server_ids = await provider.set_collection_members(
            row.server_item_id, server_item_ids, order=order, append=append
        )
        async with self._access.database.read_session() as session:
            library_items = await CollectionRepository(session).library_items(
                row.media_type, row.library_id or ""
            )
        members = stored_ids(server_ids, library_items)
        async with self._access.database.write_session() as session:
            current = await self._access.require(session, row.id or 0, row.media_type)
            await CollectionRepository(session).replace_members(row.id or 0, members)
            current.server_item_id = row.server_item_id
            current.server_link = row.server_link
            current.server_path = row.server_path
            current.kind = CollectionKind.REGULAR
            current.child_count = len(server_ids)
            current.order_type = order
            current.updated_at = utc_now()
            session.add(current)
        row.kind = CollectionKind.REGULAR
        await self._access.updated(row.id)

    async def set_members(
        self,
        collection_id: int,
        media_type: MediaType,
        body: CollectionMembersUpdate,
        *,
        sync: bool = True,
    ) -> CollectionDetail:
        """Replace members, in an order the server supports."""
        self._validator.display(body, media_type, smart=False)
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(
                    session, collection_id, media_type
                )
            if row.kind is CollectionKind.SMART:
                raise PublicServiceError(
                    422, "Smart collection members are controlled by their criteria"
                )
            items = order_items(
                resolve_members(
                    body.member_ids,
                    await self._access.library_items(row.library_id or "", media_type),
                ),
                body.order_type,
            )
            if sync:
                await self._display.push(
                    row,
                    saved_options(row, None).model_copy(
                        update={"order_type": body.order_type}
                    ),
                )
                await self.set_members_locked(row, items, body.order_type)
            else:
                await self._store_members(row, items, body.order_type)
        return await self._reader.get(collection_id, media_type)

    async def _store_members(
        self, row: MediaCollection, items: list[MediaItem], order: CollectionOrder
    ) -> None:
        """Save members in Overture only; the next sync sends them."""
        async with self._access.database.write_session() as session:
            current = await self._access.require(session, row.id or 0, row.media_type)
            await CollectionRepository(session).replace_members(
                row.id or 0, [item.id or 0 for item in items]
            )
            current.child_count = len(items)
            current.order_type = order
            current.unsynced = outdates_server(current)
            current.updated_at = utc_now()
            session.add(current)
        await self._access.updated(row.id)

    # Rules

    async def save_rule(
        self, collection_id: int, media_type: MediaType, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        """Persist validated criteria; the next sync applies them."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(
                    session, collection_id, media_type
                )
            if row.generated_value is not None:
                raise PublicServiceError(
                    422,
                    "Its group's collection set decides its criteria; edit the set",
                )
            return await self.save_rule_locked(row, body)

    async def save_rule_locked(
        self, row: MediaCollection, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        collection_id = row.id or 0
        async with self._access.database.read_session() as session:
            existing = await CollectionRepository(session).rule(collection_id)
            policy = await self._access.policy(
                session, row.media_type, row.collection_group, body
            )
        self._validator.rule(row.media_type, body, policy)
        # A new rule keeps the order of a list it selects from, where it can.
        keep_source_order = (
            existing is None
            and body.order_type is None
            and CollectionOrder.CUSTOM
            in available_orders(
                self._access.server_type, row.media_type, smart=body.smart
            )
            and any(
                condition.source.type in ORDERED_SOURCES
                for condition in body.criteria.source_conditions()
            )
        )
        if keep_source_order:
            body = body.model_copy(update={"order_type": CollectionOrder.CUSTOM})
            await self._display.push(
                row,
                saved_options(row, None).model_copy(
                    update={"order_type": CollectionOrder.CUSTOM}
                ),
                body,
            )
        franchise = min(franchise_ids(body.criteria), default=None)
        async with self._access.database.write_session() as session:
            saved_row = await self._access.require(
                session, collection_id, row.media_type
            )
            rule = await CollectionRepository(session).rule(collection_id)
            new_rule = rule_row(collection_id, body)
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
        await self._access.updated(collection_id)
        result = rule_read(rule)
        if result is None:
            raise RuntimeError("A saved rule must exist")
        return result

    async def replace_kind(self, row: MediaCollection, *, smart: bool) -> None:
        """Plex cannot convert a collection's kind, so the server copy is replaced."""
        if (
            row.server_item_id is not None
            and (row.kind is CollectionKind.SMART) != smart
        ):
            await self.delete_server_collection(row)
            row.server_item_id = None

    async def adoption_plan(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionAdoptionPlan:
        """What adopting a collection made outside Overture would keep.

        A regular collection keeps its current members; a Plex smart collection
        keeps its filter, read back into criteria. Movies that all belong to one
        TMDB collection keep it as their source, and it gives them art and a theme.

        Raises:
            PublicServiceError: 409 when it already has a rule, 422 when its
                Plex filter has terms criteria cannot express.
        """
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            row = await self._access.require(session, collection_id, media_type)
            if await repo.rule(collection_id) is not None:
                raise PublicServiceError(409, "Overture already manages it")
            members = await repo.members(collection_id)
        franchise = shared_franchise(members)
        return CollectionAdoptionPlan(
            rule=await self._smart_adoption_rule(row)
            if row.kind is CollectionKind.SMART
            else CollectionRuleWrite(
                criteria=member_criteria(
                    row,
                    members,
                    # Only TMDB can list a franchise's parts on each sync.
                    franchise=franchise
                    if self._access.app_config.tmdb_configured
                    else None,
                )
            ),
            tmdb_collection_id=row.tmdb_collection_id or franchise,
        )

    async def adopt(
        self, collection_id: int, media_type: MediaType, body: CollectionAdoption
    ) -> CollectionDetail:
        """Give a collection made outside Overture the rule its plan keeps."""
        plan = await self.adoption_plan(collection_id, media_type)
        body = body.model_copy(update={"group": collection_group(body.group)})
        async with self._access.locked(collection_id):
            async with self._access.database.write_session() as session:
                stored = await self._access.require(session, collection_id, media_type)
                stored.collection_group = body.group
                stored.tmdb_collection_id = plan.tmdb_collection_id
                session.add(stored)
            await self.save_rule_locked(stored, plan.rule)
        return await self._reader.get(collection_id, media_type)

    async def orphan(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionDetail:
        """Stop managing a collection; the server keeps it, listed as unmanaged.

        The reverse of adoption: the rule and group go, and the collection is
        listed under Unmanaged until it is adopted again.

        Raises:
            PublicServiceError: 409 when it has no server copy to keep, its
                group's set made it, or its Plex filter reads Overture's labels.
        """
        async with (
            self._access.locked(collection_id),
            self._access.database.write_session() as session,
        ):
            row = await self._access.require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
            if rule is None:
                raise PublicServiceError(409, "Overture does not manage it")
            if row.server_item_id is None:
                raise PublicServiceError(
                    409, "It is not on the media server; delete it instead"
                )
            if row.generated_value is not None:
                raise PublicServiceError(
                    409, "Its group's set made it; remove its value from the set"
                )
            if rule.smart and rule_criteria(rule).source_conditions():
                raise PublicServiceError(
                    409,
                    "Its Plex filter reads labels only Overture keeps; "
                    "make it a regular collection first",
                )
            await session.delete(rule)
            row.collection_group = None
            row.unsynced = False
            row.active_start_mmdd = None
            row.active_end_mmdd = None
            row.delete_when_inactive = None
            row.tmdb_collection_id = row.provider_tmdb_id
            row.updated_at = utc_now()
            session.add(row)
        await self._access.changed()
        return await self._reader.get(collection_id, media_type)

    async def _smart_adoption_rule(self, row: MediaCollection) -> CollectionRuleWrite:
        provider = self._access.provider()
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

    # Selections and flags

    async def forget_selections(
        self, collection_id: int, media_type: MediaType, *, artwork: bool
    ) -> None:
        """Forget saved art or theme choices; server images and files stay."""
        async with (
            self._access.asset_locks.acquire(f"collection:{collection_id}"),
            self._access.database.write_session() as session,
        ):
            row = await self._access.require_managed(session, collection_id, media_type)
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
        await self._access.updated(collection_id)

    async def set_monitored(
        self, collection_id: int, media_type: MediaType, monitored: bool
    ) -> MonitoredResponse:
        """Set whether a collection is monitored."""
        async with self._access.database.write_session() as session:
            row = await self._access.require_managed(session, collection_id, media_type)
            row.monitored = monitored
            row.updated_at = utc_now()
            session.add(row)
        await self._access.updated(collection_id)
        return MonitoredResponse(monitored=monitored)

    async def bulk_set_monitored(
        self, collection_ids: list[int], media_type: MediaType, monitored: bool
    ) -> BulkMonitorResponse:
        """Set the monitored flag for multiple collections at once."""
        self._access.provider()
        async with self._access.database.write_session() as db:
            updated = await CollectionRepository(db).bulk_set_monitored(
                collection_ids, media_type, monitored, timestamp=utc_now()
            )
        await self._access.changed()
        return BulkMonitorResponse(updated=updated)
