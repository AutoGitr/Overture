"""Changing one collection: creating, editing, membership, rules and removal."""

lazy from collections.abc import Collection, Iterable, Mapping, Sequence

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import (
    AssetScope,
    CollectionKind,
    CollectionOrder,
    MediaType,
    ServerType,
)
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.collection_items import (
    CollectionItem,
    CollectionItemRepository,
)
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
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
lazy from ...utils.collection_fields import available_orders, kept_order
lazy from ...utils.collection_formats import literal_template
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..downloads.service import DownloadService
lazy from ..needs import apply_needs
lazy from . import COLLECTIONS_LOCK
lazy from .access import CollectionAccess
lazy from .copies import CopyKey, ServerCopy, copy_keys, copy_libraries
lazy from .criteria import order_items
lazy from .destinations import place_collection
lazy from .display import DISPLAY_OVERRIDES, CollectionDisplay, resolved_order
lazy from .membership import Membership, resolve_members
lazy from .reader import CollectionReader
lazy from .rules import (
    ORDERED_SOURCES,
    apply_libraries,
    outdates_server,
    rule_read,
    rule_row,
    sole_franchise,
    title_taken,
)
lazy from .sync_outcome import CopyChange
lazy from .validation import CollectionValidator

#: What a server copy holds: a title, or ``(server, item)`` for an item no
#: sync has stored yet.
type Held = int | tuple[int, str]


def _required_group(body: CollectionOptions) -> str:
    """The group a managed collection names; every one belongs to a group.

    Raises:
        PublicServiceError: 422 when it names none.
    """
    if body.collection_group is None:
        raise PublicServiceError(422, "Choose a group for the collection")
    return body.collection_group


def _require_movies(
    tmdb_collection_id: int | None, media_types: Iterable[MediaType]
) -> None:
    if tmdb_collection_id is not None and MediaType.MOVIE not in media_types:
        raise PublicServiceError(422, "TMDB collections hold movies only")


def relinks(row: MediaCollection, body: CollectionOptions) -> bool:
    """Whether saving *body* changes the TMDB collection *row* links titles by."""
    return (
        "tmdb_collection_id" in body.model_fields_set
        and body.tmdb_collection_id != row.tmdb_collection_id
    )


def _server_ids(
    wanted: Mapping[str, list[CollectionItem]], library_ids: Collection[str]
) -> list[str]:
    """The server's IDs of what these libraries hold, in their order."""
    return [
        item.server_item_id
        for library_id, items in wanted.items()
        if library_id in library_ids
        for item in items
        if item.server_item_id
    ]


async def store_placement(
    session: AsyncSession,
    saved: MediaCollection,
    row: MediaCollection,
    registry: ProviderRegistry,
) -> None:
    """Store where *row*'s copies are as *saved*'s, held by no other collection.

    A server can give a collection it makes the ID of one it deleted:
    Jellyfin derives a BoxSet's from its folder, named after the title it
    was made with. Another collection still holding that ID holds a copy
    the server no longer has, so it lets go: an unmanaged one goes, as when
    a library sync finds its collection gone, and a managed one forgets the
    copy, which its next sync makes again.
    """
    placed = set(copy_keys(row.libraries)) - set(copy_keys(saved.libraries))
    save_placement(saved, row)
    place_collection(saved, registry)
    session.add(saved)
    repository = CollectionRepository(session)
    for other in await repository.holding(placed, besides=saved.id or 0):
        if other.rule is None:
            await repository.delete_ids([other.id or 0])
            continue
        released = await repository.clear_server_copies(
            other.id or 0, utc_now(), placed
        )
        if released is not None:
            place_collection(released, registry)
            session.add(released)


def save_placement(saved: MediaCollection, row: MediaCollection) -> None:
    """Store which server collection holds each library, and where it keeps it."""
    placed = {
        part.library_id: (part.server_item_id, part.server_path)
        for part in row.libraries
    }
    for part in saved.libraries:
        part.server_item_id, part.server_path = placed.get(
            part.library_id, (None, None)
        )


class CollectionEditor:
    """Create, edit and remove collections; only syncs and removals reach the server.

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
        downloads: DownloadService,
    ) -> None:
        self._access = access
        self._validator = validator
        self._membership = membership
        self._display = display
        self._reader = reader
        self._downloads = downloads

    # Creating

    async def create(
        self, body: CollectionCreate, *, generated_value: str | None = None
    ) -> CollectionDetail:
        """Save a new collection in Overture; the next sync puts it on the server.

        *generated_value* marks a collection its group's set creates.
        """
        overrides = body.model_dump(include=body.model_fields_set & DISPLAY_OVERRIDES)
        body = body.model_copy(update={"rule": body.rule.model_copy(update=overrides)})
        rule = body.rule
        smart = rule.smart
        scopes = await self._access.scopes(rule.libraries, smart=smart)
        types = {scope.library_id: scope.media_type for scope in scopes}
        self._validator.display(
            body,
            set(types.values()),
            smart=smart,
            servers=self._access.server_types(types),
        )
        group = _required_group(body)
        _require_movies(body.tmdb_collection_id, types.values())
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(
                session, await self._access.group(session, body.collection_group), rule
            )
        self._validator.rule(types, rule, policy)
        body = body.model_copy(update={"order_type": resolved_order(body, policy)})
        async with self._access.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._access.database.read_session() as session:
                existing = await CollectionRepository(session).list_listed()
            if any(
                row.title.casefold() == body.title.casefold()
                and not types.keys().isdisjoint(row.library_ids)
                for row in existing
            ):
                raise PublicServiceError(409, title_taken(body.title))
            now = utc_now()
            row = MediaCollection(
                kind=CollectionKind.SMART if smart else CollectionKind.REGULAR,
                generated_value=generated_value,
                unsynced=True,
                last_synced_at=now,
                created_at=now,
                updated_at=now,
                summary_source=body.summary,
                **body.model_dump(exclude={"rule", "collection_group"}),
            )
            apply_libraries(row, rule.libraries, types)
            effective = await self._display.effective(row, body, rule)
            row.sqlmodel_update(
                effective.model_dump(exclude={"rule", "collection_group"})
            )
            async with self._access.database.write_session() as session:
                if row.tmdb_collection_id is None:
                    row.tmdb_collection_id = sole_franchise(rule.libraries)
                row.group = await CollectionRepository(session).ensure_group(group)
                session.add(row)
                await session.flush()
                row.rule = rule_row(row.id or 0, rule)
                place_collection(row, self._access.provider_registry)
                await apply_needs(session, collections=[row])
                session.add(row)
        await self._access.changed()
        return await self._reader.get(row.id or 0)

    # Display options

    async def update(
        self, collection_id: int, body: CollectionOptions
    ) -> CollectionDetail:
        """Save display options in Overture; the next sync sends them."""
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
            await self.update_locked(row, body, push=False)
        await self._access.updated(collection_id, titles=relinks(row, body))
        return await self._reader.get(collection_id)

    async def update_locked(
        self, row: MediaCollection, body: CollectionOptions, *, push: bool
    ) -> list[CopyChange]:
        """Save display choices, and with *push* send them to the server copies.

        Without *push* the collection is marked as holding changes the server
        lacks, which the next sync sends. Returns the copies whose server
        refused them.
        """
        overrides: dict[str, object] = {}
        if body.sort_title is not None and body.sort_title_format is None:
            overrides["sort_title_format"] = literal_template(body.sort_title)
        if body.summary is not None and body.summary_format is None:
            overrides["summary_format"] = literal_template(body.summary)
        body = body.model_copy(update=overrides)
        self._validator.display(
            body,
            row.media_types,
            smart=row.kind is CollectionKind.SMART,
            servers=self._access.server_types(row.library_ids),
        )
        if body.summary is not None:
            row.summary_source = body.summary
        display = body.model_dump(include=body.model_fields_set & DISPLAY_OVERRIDES)
        rule = row.rule
        # Only a managed collection belongs to a group, and every one names one.
        group = _required_group(body) if rule is not None else None
        if rule is not None:
            rule.sqlmodel_update(display)
        refused: list[CopyChange] = []
        if push:
            effective, refused = await self._display.push(row, body, rule)
        else:
            effective = await self._display.effective(row, body, rule)
        summary_source = row.summary_source
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0)
            fields = effective.model_dump(exclude={"collection_group"})
            fields["summary_source"] = summary_source
            if group is not None:
                saved.group = await CollectionRepository(session).ensure_group(group)
            if "tmdb_collection_id" not in body.model_fields_set:
                fields.pop("tmdb_collection_id")
            saved.sqlmodel_update(fields)
            saved.updated_at = utc_now()
            if not push:
                saved.unsynced = outdates_server(saved)
            if saved.rule is not None and display:
                saved.rule.sqlmodel_update(display)
                session.add(saved.rule)
            # Its group and TMDB collection decide what it needs; a pushed
            # change is part of a sync, whose post-sync step records that.
            if not push:
                await apply_needs(session, collections=[saved])
            session.add(saved)
        return refused

    # Removing

    async def delete_copies(self, copies: Iterable[CopyKey]) -> list[CopyKey]:
        """Delete server collections, by server and ID; return those deleted.

        An absent one counts as deleted. A copy on a server no longer
        configured is left for its return.
        """
        deleted: list[CopyKey] = []
        for server_id, server_item_id in dict.fromkeys(copies):
            if not self._access.configured(server_id):
                continue
            try:
                await self._access.provider(server_id).delete_collection(server_item_id)
            except MediaServerError as exc:
                if exc.upstream_status_code != 404:
                    raise
            deleted.append((server_id, server_item_id))
        return deleted

    async def delete_locked(
        self, row: MediaCollection
    ) -> list[tuple[int, tuple[str, ...]]]:
        """Delete a collection from the servers and Overture.

        Returns the server collections deleted, by server and libraries.
        """
        collection_id = row.id or 0
        held = copy_libraries(row.copies)
        deleted = await self.delete_copies(held)
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
        return [(key[0], held[key]) for key in deleted]

    async def withhold_locked(
        self, row: MediaCollection
    ) -> list[tuple[int, tuple[str, ...]]]:
        """Remove a collection from the servers while keeping its Overture rule.

        Returns the server collections deleted, by server and libraries.
        """
        collection_id = row.id or 0
        held = copy_libraries(row.copies)
        deleted = await self.delete_copies(held)
        async with self._access.database.write_session() as session:
            saved = await CollectionRepository(session).clear_server_copies(
                collection_id, utc_now()
            )
            if saved is not None:
                place_collection(saved, self._access.provider_registry)
                session.add(saved)
        for part in row.libraries:
            part.server_item_id = None
        await self._access.changed()
        return [(key[0], held[key]) for key in deleted]

    async def retire_libraries(
        self, row: MediaCollection
    ) -> list[tuple[int, tuple[str, ...]]]:
        """Finish removing libraries a save took out of the collection.

        Returns the server collections deleted, by server and libraries.
        """
        leaving = [part for part in row.libraries if part.criteria is None]
        if not leaving:
            return []
        staying = set(copy_keys(row.libraries)) - set(copy_keys(leaving))
        held = copy_libraries(leaving)
        deleted = await self.delete_copies(key for key in held if key not in staying)
        ids = {part.library_id for part in leaving}
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0)
            saved.libraries = [p for p in saved.libraries if p.library_id not in ids]
            place_collection(saved, self._access.provider_registry)
            session.add(saved)
        row.libraries = [p for p in row.libraries if p.library_id not in ids]
        return [(key[0], held[key]) for key in deleted]

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
        wanted: Mapping[str, list[CollectionItem]],
        order: CollectionOrder,
        *,
        append: bool = False,
    ) -> list[CopyChange]:
        """Make the ordered items, by library, the regular collection's members.

        Returns what that did to each server collection.
        """
        held, changes = await self.place_members(
            row, self._access.copies(row), wanted, order, append=append
        )
        await self.store_members(row, held, order, kind=CollectionKind.REGULAR)
        return changes

    async def place_members(
        self,
        row: MediaCollection,
        copies: Sequence[ServerCopy],
        wanted: Mapping[str, list[CollectionItem]],
        order: CollectionOrder,
        *,
        append: bool = False,
    ) -> tuple[list[Held], list[CopyChange]]:
        """Make the ordered items, by library, the members of *copies* on their servers.

        Libraries saved apart on a server that spans them fold into one copy,
        and a library left with nothing to hold loses its own. Returns what
        the copies hold, each once, in order (see :meth:`held`), and what the
        sync did to each. A server that refuses its copy's sync is reported
        and leaves the others to go on; what it made before refusing stays
        placed, so the next sync finds it rather than making another, and
        its libraries keep the members Overture holds for them.
        """
        members: dict[Held, None] = {}
        changes: list[CopyChange] = []
        for copy in copies:
            try:
                held = await self._place_copy(
                    row, copy, wanted, order, changes, append=append
                )
            except MediaServerError as exc:
                changes.append(CopyChange.failed(copy, exc))
                held = await self.stored_members(row, copy)
            members.update(dict.fromkeys(held))
        return list(members), changes

    async def existing(
        self, row: MediaCollection, copy: ServerCopy, *, smart: bool
    ) -> str | None:
        """Place *copy* in the server's collection of the title, if it holds one.

        Making a collection is one request a server can carry out and still
        fail, as on a timeout, so the collection made then is found here by
        its title before another is made. Only one of the same kind (*smart*
        or regular) that no Overture collection holds is taken. Returns the ID
        of the one taken.
        """
        found = await self._access.provider(copy.server_id).find_collection(
            copy.lead.library_id, row.title, copy.lead.media_type
        )
        if found is None or found.smart is not smart:
            return None
        async with self._access.database.read_session() as session:
            if await CollectionRepository(session).find_server(
                copy.server_id, found.id
            ):
                return None
        copy.place(found.id, found.path)
        return found.id

    async def stored_members(
        self, row: MediaCollection, copy: ServerCopy
    ) -> list[Held]:
        """The members Overture holds for *copy*'s libraries since its last sync.

        They stand for a copy whose server refused this sync.
        """
        async with self._access.database.read_session() as session:
            stored = await CollectionItemRepository(session).members(row.id or 0)
        return [item.id for item in stored if item.library_id in copy.library_ids]

    async def _place_copy(
        self,
        row: MediaCollection,
        copy: ServerCopy,
        wanted: Mapping[str, list[CollectionItem]],
        order: CollectionOrder,
        changes: list[CopyChange],
        *,
        append: bool,
    ) -> list[Held]:
        """Make *copy* hold its libraries' wanted items; return what it holds.

        What it did goes to *changes*.
        """
        provider = self._access.provider(copy.server_id)
        libraries = copy.library_order
        ids = _server_ids(wanted, copy.library_ids)
        if await self.delete_copies(
            (copy.server_id, identity) for identity in copy.surplus_ids
        ):
            changes.append(
                CopyChange(
                    copy.server_id,
                    libraries,
                    deleted="merged into the server's one collection for them",
                )
            )
        target = copy.server_item_id
        if target is None and ids:
            target = await self.existing(row, copy, smart=False)
        created = target is None
        if target is None:
            if not ids:
                changes.append(CopyChange(copy.server_id, libraries, absent=True))
                return []
            server = await provider.create_collection(
                copy.lead.library_id, row.title, copy.lead.media_type, ids
            )
            target = server.id
            copy.place(target, server.path)
        elif not ids and not append:
            await self.delete_copies([(copy.server_id, target)])
            copy.place(None)
            changes.append(
                CopyChange(
                    copy.server_id,
                    libraries,
                    deleted="no title there meets its rule any more",
                )
            )
            return []
        copy.place(target)
        write = await provider.set_collection_members(
            target,
            ids,
            order=kept_order(
                order, provider.server_type, copy.lead.media_type, smart=False
            ),
            append=append,
        )
        changes.append(
            CopyChange(
                copy.server_id,
                libraries,
                created=created,
                added=0 if created else write.added,
                removed=write.removed,
                held=len(write.held),
            )
        )
        return await self.held(copy.server_id, write.held)

    async def held(self, server_id: int, server_item_ids: Sequence[str]) -> list[Held]:
        """What a server's items are, in their order: titles, or items unknown yet.

        An item no sync has stored yet still counts, as that server's own.
        """
        async with self._access.database.read_session() as session:
            by_server_id = await CollectionItemRepository(
                session
            ).item_ids_by_server_id(server_id, server_item_ids)
        return [by_server_id.get(i, (server_id, i)) for i in server_item_ids]

    async def store_members(
        self,
        row: MediaCollection,
        members: Sequence[Held],
        order: CollectionOrder,
        *,
        kind: CollectionKind,
    ) -> None:
        """Store what the server copies hold now, and where they are.

        Its titles become its members; items no sync stored yet count too.
        """
        async with self._access.database.write_session() as session:
            current = await self._access.require(session, row.id or 0)
            await CollectionRepository(session).replace_members(
                row.id or 0,
                [
                    member
                    for member in dict.fromkeys(members)
                    if isinstance(member, int)
                ],
            )
            await store_placement(session, current, row, self._access.provider_registry)
            current.kind = kind
            current.child_count = len(set(members))
            current.order_type = order
            current.updated_at = utc_now()
            session.add(current)
        row.kind = kind
        await self._access.updated(row.id, titles=True)

    async def _chosen_members(
        self, row: MediaCollection, body: CollectionMembersUpdate
    ) -> dict[str, list[CollectionItem]]:
        """The members chosen by hand, in their order, by library."""
        items = [
            item
            for part in row.libraries
            for item in await self._access.library_items(
                part.library_id, part.media_type
            )
        ]
        wanted: dict[str, list[CollectionItem]] = {
            p.library_id: [] for p in row.libraries
        }
        for item in order_items(
            resolve_members(body.member_ids, items), body.order_type
        ):
            wanted[item.library_id].append(item)
        return wanted

    async def set_members(
        self, collection_id: int, body: CollectionMembersUpdate
    ) -> CollectionDetail:
        """Save members chosen by hand, in Overture; the next sync sends them."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
            self._validator.display(
                body,
                row.media_types,
                smart=False,
                servers=self._access.server_types(row.library_ids),
            )
            if row.kind is CollectionKind.SMART:
                raise PublicServiceError(
                    422, "Smart collection members are controlled by their criteria"
                )
            await self._store_members(
                row, await self._chosen_members(row, body), body.order_type
            )
        return await self._reader.get(collection_id)

    async def _store_members(
        self,
        row: MediaCollection,
        wanted: Mapping[str, list[CollectionItem]],
        order: CollectionOrder,
    ) -> None:
        ids = [item.id for items in wanted.values() for item in items]
        async with self._access.database.write_session() as session:
            current = await self._access.require(session, row.id or 0)
            await CollectionRepository(session).replace_members(row.id or 0, ids)
            current.child_count = len(ids)
            current.order_type = order
            current.unsynced = outdates_server(current)
            current.updated_at = utc_now()
            session.add(current)
        await self._access.updated(row.id, titles=True)

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
            policy = await self._access.policy(session, row.group, body)
        self._validator.rule(types, body, policy)
        # A new rule keeps the order of a list it selects from, where it can.
        keep_source_order = (
            row.rule is None
            and body.order_type is None
            and any(
                all(
                    CollectionOrder.CUSTOM
                    in available_orders(
                        server,
                        media_type,
                        smart=body.smart and server is ServerType.PLEX,
                    )
                    for media_type in types.values()
                )
                for server in self._access.server_types(types)
            )
            and any(
                condition.source.type in ORDERED_SOURCES
                for library in body.libraries
                for condition in library.criteria.source_conditions()
            )
        )
        if keep_source_order:
            body = body.model_copy(update={"order_type": CollectionOrder.CUSTOM})
        franchise = sole_franchise(body.libraries)
        async with self._access.database.write_session() as session:
            saved_row = await self._access.require(session, collection_id)
            rule = saved_row.rule
            new_rule = rule_row(collection_id, body)
            if rule is None:
                rule = saved_row.rule = new_rule
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
            place_collection(saved_row, self._access.provider_registry)
            await apply_needs(session, collections=[saved_row])
            session.add(saved_row)
            await session.flush()
            result = rule_read(rule, saved_row)
        await self._access.updated(
            collection_id,
            titles=franchise is not None and franchise != row.tmdb_collection_id,
        )
        if result is None:
            raise RuntimeError("A saved rule must exist")
        return result

    async def replace_kind(self, row: MediaCollection, *, smart: bool) -> None:
        """Plex cannot convert a collection's kind, so its Plex copies are replaced.

        On another server a collection is regular either way.
        """
        if (row.kind is CollectionKind.SMART) == smart:
            return
        plex = [part for part in row.libraries if self._access.plex(part.library_id)]
        await self.delete_copies(copy_keys(plex))
        for part in plex:
            part.server_item_id = None
            part.server_path = None

    # Selections and flags

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
        self._access.require_collections()
        async with self._access.database.write_session() as db:
            updated = await CollectionRepository(db).bulk_set_monitored(
                collection_ids, monitored, timestamp=utc_now()
            )
        await self._access.changed()
        return BulkMonitorResponse(updated=updated)
