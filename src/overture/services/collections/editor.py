"""Changing one collection: creating, editing, membership, rules and removal."""

lazy import urllib.parse
lazy from collections.abc import Collection, Iterable, Mapping, Sequence
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
    CollectionLibraryCriteria,
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
lazy from .access import CollectionAccess, LibraryScope
lazy from .criteria import order_items
lazy from .display import DISPLAY_OVERRIDES, CollectionDisplay, saved_options
lazy from .fields import available_orders
lazy from .membership import Membership, resolve_members, stored_ids
lazy from .plex_query import (
    UnmappableFilterError,
    decompile_plex_query,
    plex_field,
    plex_field_keys,
    plex_term_key,
)
lazy from .reader import CollectionReader
lazy from .rules import (
    ORDERED_SOURCES,
    TITLE_TAKEN,
    apply_libraries,
    criteria_of,
    franchise_ids,
    member_criteria,
    outdates_server,
    rule_read,
    rule_row,
    shared_franchise,
)
lazy from .sources import SourceResolver
lazy from .validation import CollectionValidator


def _require_movies(
    tmdb_collection_id: int | None, media_types: Iterable[MediaType]
) -> None:
    if tmdb_collection_id is not None and MediaType.MOVIE not in media_types:
        raise PublicServiceError(422, "TMDB collections hold movies only")


def _server_ids(
    wanted: Mapping[str, list[MediaItem]], library_ids: Collection[str]
) -> list[str]:
    """The server's IDs of what these libraries hold, in their order."""
    return [
        item.server_item_id
        for library_id, items in wanted.items()
        if library_id in library_ids
        for item in items
        if item.server_item_id
    ]


def save_placement(saved: MediaCollection, row: MediaCollection) -> None:
    """Store which server collection now holds each library."""
    placed = {part.library_id: part.server_item_id for part in row.libraries}
    for part in saved.libraries:
        part.server_item_id = placed.get(part.library_id)


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
        scopes = await self._access.scopes(rule.libraries)
        types = {scope.library_id: scope.media_type for scope in scopes}
        self._validator.display(body, set(types.values()), smart=smart)
        group = collection_group(body.collection_group)
        body = body.model_copy(update={"collection_group": group})
        _require_movies(body.tmdb_collection_id, types.values())
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(
                session, await self._access.group(session, body.collection_group), rule
            )
        self._validator.rule(types, rule, policy)
        if "order_type" not in body.model_fields_set:
            body = body.model_copy(update={"order_type": policy.order_type})
        wanted = await self._initial_members(body, scopes)
        source_summary = await self._sources.summary(rule.libraries)
        # The minimum and the season decide only whether the server has it
        # yet; Overture keeps it either way, and a later sync creates it.
        total = sum(len(items) for items in wanted.values())
        withhold = (not smart and total < policy.minimum_items) or (
            policy.delete_when_inactive
            and not self._access.active(
                body.active_start_mmdd or policy.active_start_mmdd,
                body.active_end_mmdd or policy.active_end_mmdd,
            )
        )
        server = self._access.server_type
        async with self._access.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._access.database.read_session() as session:
                existing = await CollectionRepository(session).list_listed()
            if any(
                row.server_type is server
                and row.title.casefold() == body.title.casefold()
                and not types.keys().isdisjoint(row.library_ids)
                for row in existing
            ):
                raise PublicServiceError(409, TITLE_TAKEN)
            now = utc_now()
            row = MediaCollection(
                server_type=server,
                kind=CollectionKind.SMART if smart else CollectionKind.REGULAR,
                generated_value=generated_value,
                unsynced=not sync,
                last_synced_at=now,
                created_at=now,
                updated_at=now,
                **body.model_dump(exclude={"rule", "collection_group"}),
            )
            apply_libraries(row, rule.libraries, types)
            if sync and not withhold:
                wanted = await self._create_on_server(row, body, wanted, scopes)
            await self._configure_new(
                row, body, rule, wanted, smart=smart, source_summary=source_summary
            )
            async with self._access.database.write_session() as session:
                if row.tmdb_collection_id is None:
                    row.tmdb_collection_id = min(
                        franchise_ids(rule.libraries), default=None
                    )
                row.group = await CollectionRepository(session).ensure_group(
                    server, group
                )
                session.add(row)
                await session.flush()
                await CollectionRepository(session).replace_members(
                    row.id or 0,
                    [item.id or 0 for items in wanted.values() for item in items],
                )
                saved_rule = rule_row(row.id or 0, rule)
                saved_rule.source_summary = source_summary
                session.add(saved_rule)
        await self._access.changed()
        return await self._reader.get(row.id or 0)

    async def _configure_new(
        self,
        row: MediaCollection,
        body: CollectionCreate,
        rule: CollectionRuleWrite,
        wanted: Mapping[str, list[MediaItem]],
        *,
        smart: bool,
        source_summary: str | None,
    ) -> None:
        """Apply display options and order to a new collection, or remove it."""
        provider = self._access.provider()
        try:
            row.child_count = sum(len(items) for items in wanted.values())
            row.summary_source = body.summary
            effective = await self._display.push(
                row, body, rule, source_summary=source_summary
            )
            row.sqlmodel_update(
                effective.model_dump(exclude={"rule", "collection_group"})
            )
            if smart:
                return
            for copy in self._access.copies(row):
                ids = _server_ids(wanted, copy.library_ids)
                if copy.server_item_id is not None and ids:
                    await provider.set_collection_members(
                        copy.server_item_id, ids, order=body.order_type
                    )
        except Exception:
            # Overture records nothing, so the server keeps no half-made copy.
            for server_id in row.server_ids:
                with suppress(MediaServerError):
                    await provider.delete_collection(server_id)
            raise

    async def _initial_members(
        self, body: CollectionCreate, scopes: Sequence[LibraryScope]
    ) -> dict[str, list[MediaItem]]:
        """What the criteria select; Plex fills a smart collection itself."""
        if body.rule.smart:
            return {scope.library_id: [] for scope in scopes}
        return await self._membership.wanted_in(
            scopes, order=body.order_type, limit=body.rule.limit
        )

    async def _create_on_server(
        self,
        row: MediaCollection,
        body: CollectionCreate,
        wanted: Mapping[str, list[MediaItem]],
        scopes: Sequence[LibraryScope],
    ) -> dict[str, list[MediaItem]]:
        """Create the server's collections; Plex decides a smart one's members.

        A library with nothing to hold gets no server collection until it has.
        """
        provider = self._access.provider()
        by_library = {scope.library_id: scope for scope in scopes}
        members = dict(wanted)
        try:
            for copy in self._access.copies(row):
                lead = copy.lead
                if body.rule.smart:
                    scope = by_library[lead.library_id]
                    server = await provider.create_smart_collection(
                        lead.library_id,
                        body.title,
                        lead.media_type,
                        await self._membership.smart_query(
                            scope, body.order_type, body.rule.limit
                        ),
                    )
                    by_server_id = {
                        item.server_item_id: item
                        for item in scope.items
                        if item.server_item_id
                    }
                    members[lead.library_id] = [
                        by_server_id[identity]
                        for identity in server.member_ids
                        if identity in by_server_id
                    ]
                else:
                    ids = _server_ids(wanted, copy.library_ids)
                    if not ids:
                        continue
                    server = await provider.create_collection(
                        lead.library_id, body.title, lead.media_type, ids
                    )
                copy.place(server.id)
                row.server_path = row.server_path or server.path
        except Exception:
            for server_id in row.server_ids:
                with suppress(MediaServerError):
                    await provider.delete_collection(server_id)
            raise
        return members

    # Display options

    async def update(
        self, collection_id: int, body: CollectionOptions, *, sync: bool = True
    ) -> CollectionDetail:
        """Edit collection metadata without touching movie or show metadata."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
            _require_movies(body.tmdb_collection_id, row.media_types)
            if row.generated_value is not None and body.title != row.title:
                raise PublicServiceError(
                    422, "Its collection set titles this collection; edit the set"
                )
            if row.kind is CollectionKind.SEPARATOR:
                raise PublicServiceError(
                    422, "Its group keeps the separator; change the group instead"
                )
            await self.update_locked(row, body, push=sync)
        await self._access.updated(collection_id)
        return await self._reader.get(collection_id)

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
            body, row.media_types, smart=row.kind is CollectionKind.SMART
        )
        if body.summary is not None:
            row.summary_source = body.summary
        display = body.model_dump(include=body.model_fields_set & DISPLAY_OVERRIDES)
        async with self._access.database.read_session() as session:
            rule = await CollectionRepository(session).rule(row.id or 0)
        group = collection_group(body.collection_group) if rule is not None else None
        if rule is not None:
            body = body.model_copy(update={"collection_group": group})
            rule.sqlmodel_update(display)
        effective = await self._display.push(row, body, rule, push=push)
        summary_source = row.summary_source
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0)
            fields = effective.model_dump(exclude={"collection_group"})
            fields["summary_source"] = summary_source
            # Only a managed collection belongs to a group.
            if group is not None:
                saved.group = await CollectionRepository(session).ensure_group(
                    saved.server_type, group
                )
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

    async def delete_server_ids(self, server_ids: Sequence[str]) -> None:
        """A server-side deletion is complete when the collection is already absent."""
        for server_id in server_ids:
            try:
                await self._access.provider().delete_collection(server_id)
            except MediaServerError as exc:
                if exc.upstream_status_code != 404:
                    raise

    async def delete_locked(self, row: MediaCollection) -> None:
        collection_id = row.id or 0
        await self.delete_server_ids(row.server_ids)
        async with self._access.database.write_session() as session:
            await self._downloads.cancel_assets(
                session, AssetScope(collection_id=collection_id)
            )
            await CollectionRepository(session).delete_ids([collection_id])
        await self._downloads.committed(session)
        if row.kind is CollectionKind.SMART:
            for part in row.libraries:
                await self._membership.prune_labels(part.library_id, part.media_type)
        await self._access.changed()

    async def withhold_locked(self, row: MediaCollection) -> None:
        """Remove a collection from the server while keeping its Overture rule."""
        collection_id = row.id or 0
        await self.delete_server_ids(row.server_ids)
        async with self._access.database.write_session() as session:
            await CollectionRepository(session).clear_server_copies(
                collection_id, utc_now()
            )
        for part in row.libraries:
            part.server_item_id = None
        await self._access.changed()

    async def retire_libraries(self, row: MediaCollection) -> None:
        """Finish removing libraries a save took out of the collection."""
        leaving = [part for part in row.libraries if part.criteria is None]
        if not leaving:
            return
        staying = {part.server_item_id for part in row.libraries} - {
            part.server_item_id for part in leaving
        }
        await self.delete_server_ids(
            [
                identity
                for identity in dict.fromkeys(p.server_item_id for p in leaving)
                if identity and identity not in staying
            ]
        )
        ids = {part.library_id for part in leaving}
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0)
            saved.libraries = [p for p in saved.libraries if p.library_id not in ids]
            session.add(saved)
        row.libraries = [p for p in row.libraries if p.library_id not in ids]

    async def withhold(self, collection_id: int) -> None:
        """Take a collection off the server, keeping it in Overture."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
            await self.withhold_locked(row)

    async def delete(
        self, collection_id: int, *, target: CollectionDeleteTarget = "both"
    ) -> StatusResponse:
        """Delete a collection and cancel its assets, preserving all media.

        Raises:
            PublicServiceError: 409 when its group's set made it, since the
                set's next sync would make it again.
        """
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
            if row.generated_value is not None:
                raise PublicServiceError(
                    409, "Its group's set made it; remove its value from the set"
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
        wanted: Mapping[str, list[MediaItem]],
        order: CollectionOrder,
        *,
        append: bool = False,
    ) -> None:
        """Make the ordered items, by library, the collection's members on the server.

        Libraries saved apart on a server that spans them fold into one copy,
        and a library left with nothing to hold loses its own.
        """
        provider = self._access.provider()
        server_ids: list[str] = []
        for copy in self._access.copies(row):
            ids = _server_ids(wanted, copy.library_ids)
            await self.delete_server_ids(copy.surplus_ids)
            target = copy.server_item_id
            if target is None:
                if not ids:
                    continue
                server = await provider.create_collection(
                    copy.lead.library_id, row.title, copy.lead.media_type, ids
                )
                target = server.id
                row.server_path = row.server_path or server.path
            elif not ids and not append:
                await self.delete_server_ids([target])
                copy.place(None)
                continue
            copy.place(target)
            server_ids += await provider.set_collection_members(
                target, ids, order=order, append=append
            )
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            items = [
                item
                for part in row.libraries
                for item in await repo.library_items(part.media_type, part.library_id)
            ]
        members = stored_ids(server_ids, items)
        async with self._access.database.write_session() as session:
            current = await self._access.require(session, row.id or 0)
            await CollectionRepository(session).replace_members(row.id or 0, members)
            save_placement(current, row)
            current.server_path = row.server_path
            current.kind = CollectionKind.REGULAR
            current.child_count = len(server_ids)
            current.order_type = order
            current.updated_at = utc_now()
            session.add(current)
        row.kind = CollectionKind.REGULAR
        await self._access.updated(row.id)

    async def _chosen_members(
        self, row: MediaCollection, body: CollectionMembersUpdate
    ) -> dict[str, list[MediaItem]]:
        """The members chosen by hand, in their order, by library."""
        items = [
            item
            for part in row.libraries
            for item in await self._access.library_items(
                part.library_id, part.media_type
            )
        ]
        wanted: dict[str, list[MediaItem]] = {p.library_id: [] for p in row.libraries}
        for item in order_items(
            resolve_members(body.member_ids, items), body.order_type
        ):
            wanted[item.library_id or ""].append(item)
        return wanted

    async def set_members(
        self, collection_id: int, body: CollectionMembersUpdate, *, sync: bool = True
    ) -> CollectionDetail:
        """Replace members, in an order the server supports."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
            self._validator.display(body, row.media_types, smart=False)
            if row.kind is CollectionKind.SMART:
                raise PublicServiceError(
                    422, "Smart collection members are controlled by their criteria"
                )
            wanted = await self._chosen_members(row, body)
            if sync:
                await self._display.push(
                    row,
                    saved_options(row, None).model_copy(
                        update={"order_type": body.order_type}
                    ),
                )
                await self.set_members_locked(row, wanted, body.order_type)
            else:
                await self._store_members(row, wanted, body.order_type)
        return await self._reader.get(collection_id)

    async def _store_members(
        self,
        row: MediaCollection,
        wanted: Mapping[str, list[MediaItem]],
        order: CollectionOrder,
    ) -> None:
        """Save members in Overture only; the next sync sends them."""
        ids = [item.id or 0 for items in wanted.values() for item in items]
        async with self._access.database.write_session() as session:
            current = await self._access.require(session, row.id or 0)
            await CollectionRepository(session).replace_members(row.id or 0, ids)
            current.child_count = len(ids)
            current.order_type = order
            current.unsynced = outdates_server(current)
            current.updated_at = utc_now()
            session.add(current)
        await self._access.updated(row.id)

    # Rules

    async def save_rule(
        self, collection_id: int, body: CollectionRuleWrite
    ) -> CollectionRuleRead:
        """Persist validated criteria; the next sync applies them."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
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
        types = await self._access.library_types(
            library.library_id for library in body.libraries
        )
        async with self._access.database.read_session() as session:
            existing = await CollectionRepository(session).rule(collection_id)
            policy = await self._access.policy(session, row.group, body)
        self._validator.rule(types, body, policy)
        # A new rule keeps the order of a list it selects from, where it can.
        keep_source_order = (
            existing is None
            and body.order_type is None
            and all(
                CollectionOrder.CUSTOM
                in available_orders(
                    self._access.server_type, media_type, smart=body.smart
                )
                for media_type in types.values()
            )
            and any(
                condition.source.type in ORDERED_SOURCES
                for library in body.libraries
                for condition in library.criteria.source_conditions()
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
        franchise = min(franchise_ids(body.libraries), default=None)
        async with self._access.database.write_session() as session:
            saved_row = await self._access.require(session, collection_id)
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
            apply_libraries(saved_row, body.libraries, types)
            if keep_source_order:
                saved_row.order_type = CollectionOrder.CUSTOM
            if franchise is not None:
                saved_row.tmdb_collection_id = franchise
            session.add(saved_row)
            await session.flush()
            result = rule_read(rule, saved_row)
        await self._access.updated(collection_id)
        if result is None:
            raise RuntimeError("A saved rule must exist")
        return result

    async def replace_kind(self, row: MediaCollection, *, smart: bool) -> None:
        """Plex cannot convert a collection's kind, so its copies are replaced."""
        if (row.kind is CollectionKind.SMART) != smart:
            await self.delete_server_ids(row.server_ids)
            for part in row.libraries:
                part.server_item_id = None

    async def adoption_plan(self, collection_id: int) -> CollectionAdoptionPlan:
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
            row = await self._access.require(session, collection_id)
            if await repo.rule(collection_id) is not None:
                raise PublicServiceError(409, "Overture already manages it")
            members = await repo.members(collection_id)
        franchise = shared_franchise(members)
        # Only TMDB can list a franchise's parts on each sync.
        kept = franchise if self._access.app_config.tmdb_configured else None
        return CollectionAdoptionPlan(
            rule=await self._smart_adoption_rule(row)
            if row.kind is CollectionKind.SMART
            else CollectionRuleWrite(
                libraries=[
                    CollectionLibraryCriteria(
                        library_id=part.library_id,
                        criteria=member_criteria(
                            row,
                            [m for m in members if m.library_id == part.library_id],
                            franchise=kept,
                        ),
                    )
                    for part in row.libraries
                ]
            ),
            tmdb_collection_id=row.tmdb_collection_id or franchise,
        )

    async def adopt(
        self, collection_id: int, body: CollectionAdoption
    ) -> CollectionDetail:
        """Give a collection made outside Overture the rule its plan keeps."""
        plan = await self.adoption_plan(collection_id)
        group = collection_group(body.group)
        async with self._access.locked(collection_id):
            async with self._access.database.write_session() as session:
                stored = await self._access.require(session, collection_id)
                stored.group = await CollectionRepository(session).ensure_group(
                    stored.server_type, group
                )
                stored.tmdb_collection_id = plan.tmdb_collection_id
                session.add(stored)
            await self.save_rule_locked(stored, plan.rule)
        return await self._reader.get(collection_id)

    async def orphan(self, collection_id: int) -> CollectionDetail:
        """Stop managing a collection; the server keeps it, listed as unmanaged.

        The reverse of adoption: the rule and group go, and the collection is
        listed under Unmanaged until it is adopted again. Plex holds a
        cross-library collection as one collection per library, which are
        unrelated once Overture stops managing them, so this row keeps the first
        and the next library sync lists the rest on their own.

        Raises:
            PublicServiceError: 409 when it has no server copy to keep, its
                group's set made it, or its Plex filter reads Overture's labels.
        """
        async with self._access.locked(collection_id):
            await self.orphan_locked(collection_id)
        await self._access.changed()
        return await self._reader.get(collection_id)

    async def orphan_locked(
        self, collection_id: int, *, set_removed: bool = False
    ) -> None:
        """Orphan a collection whose locks the caller holds.

        *set_removed* is for a group deleted with its set, which can no longer
        recreate what it made.
        """
        async with self._access.database.write_session() as session:
            row = await self._access.require(session, collection_id)
            rule = await CollectionRepository(session).rule(collection_id)
            if rule is None:
                raise PublicServiceError(409, "Overture does not manage it")
            lead = row.server_item_id
            if lead is None:
                raise PublicServiceError(
                    409, "It is not on the media server; delete it instead"
                )
            if row.generated_value is not None and not set_removed:
                raise PublicServiceError(
                    409, "Its group's set made it; remove its value from the set"
                )
            if rule.smart and any(
                self._membership.labels(part.media_type, criteria_of(part))
                for part in row.libraries
                if part.criteria is not None
            ):
                raise PublicServiceError(
                    409,
                    "Its Plex filter reads labels only Overture keeps; "
                    "make it a regular collection first",
                )
            await session.delete(rule)
            row.libraries = [p for p in row.libraries if p.server_item_id == lead]
            for part in row.libraries:
                part.criteria = None
                session.add(part)
            row.group = None
            row.generated_value = None
            row.unsynced = False
            row.active_start_mmdd = None
            row.active_end_mmdd = None
            row.delete_when_inactive = None
            row.tmdb_collection_id = row.provider_tmdb_id
            row.updated_at = utc_now()
            session.add(row)

    async def _smart_adoption_rule(self, row: MediaCollection) -> CollectionRuleWrite:
        provider = self._access.provider()
        if row.server_item_id is None:
            raise PublicServiceError(409, "The collection has no server copy")
        part = row.libraries[0]
        media_type = part.media_type
        query = await provider.smart_collection_filter(row.server_item_id)
        fields = plex_field_keys(media_type)
        names: dict[str, dict[str, str]] = {}
        for name, _ in urllib.parse.parse_qsl(query):
            key = plex_term_key(name, media_type)
            field = fields.get(key)
            if field is None or key in names or plex_field(field).type != "tag":
                continue
            choices = await provider.filter_choices(part.library_id, media_type, key)
            names[key] = dict(choices)
        try:
            decompiled = decompile_plex_query(query, media_type=media_type, names=names)
        except UnmappableFilterError as exc:
            raise PublicServiceError(422, str(exc)) from exc
        return CollectionRuleWrite(
            libraries=[
                CollectionLibraryCriteria(
                    library_id=part.library_id, criteria=decompiled.criteria
                )
            ],
            smart=True,
            order_type=decompiled.order,
            limit=decompiled.limit,
        )

    # Selections and flags

    async def forget_selections(self, collection_id: int, *, artwork: bool) -> None:
        """Forget saved art or theme choices; server images and files stay."""
        async with (
            self._access.asset_locks.acquire(f"collection:{collection_id}"),
            self._access.database.write_session() as session,
        ):
            row = await self._access.require_managed(session, collection_id)
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
        self, collection_id: int, monitored: bool
    ) -> MonitoredResponse:
        """Set whether a collection is monitored."""
        async with self._access.database.write_session() as session:
            row = await self._access.require_managed(session, collection_id)
            row.monitored = monitored
            row.updated_at = utc_now()
            session.add(row)
        await self._access.broadcast(
            "collection.monitored",
            {"collection_id": collection_id, "monitored": monitored},
        )
        return MonitoredResponse(monitored=monitored)

    async def bulk_set_monitored(
        self, collection_ids: list[int], monitored: bool
    ) -> BulkMonitorResponse:
        """Set the monitored flag for multiple collections at once."""
        self._access.provider()
        async with self._access.database.write_session() as db:
            updated = await CollectionRepository(db).bulk_set_monitored(
                collection_ids, monitored, timestamp=utc_now()
            )
        await self._access.changed()
        return BulkMonitorResponse(updated=updated)
