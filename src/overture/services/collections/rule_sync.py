"""Bringing one managed collection's server copies in line with its rule."""

lazy import logging
lazy from collections.abc import Mapping

lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import UNMANAGED_REFUSAL, CollectionKind, SyncMode
lazy from ...repositories.collection_items import (
    CollectionItem,
    CollectionItemRepository,
)
lazy from ...repositories.collections import CollectionRepository
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from .access import CollectionAccess, LibraryScope
lazy from .copies import copy_keys
lazy from .destinations import place_collection
lazy from .display import saved_options
lazy from .editor import CollectionEditor, Held, save_placement
lazy from .membership import Membership
lazy from .policy import CollectionPolicy
lazy from .post_sync import PostSync
lazy from .rules import criteria_of, library_criteria
lazy from .sources import SourceResolver
lazy from .sync_outcome import CopyChange, SyncOutcome

logger = logging.getLogger(__name__)


class RuleSync:
    """Resolve a rule's members and make them the server collections'."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        membership: Membership,
        editor: CollectionEditor,
        post_sync: PostSync,
        sources: SourceResolver,
    ) -> None:
        self._access = access
        self._membership = membership
        self._editor = editor
        self._post_sync = post_sync
        self._sources = sources

    async def sync(self, collection_id: int) -> SyncOutcome:
        """Resolve every source before changing any server membership.

        Returns what the sync did on each server.
        """
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                items = CollectionItemRepository(session)
                row = await self._access.require(session, collection_id)
                rule = row.rule
                policy = await self._access.policy(session, row.group, rule)
                if rule is None:
                    raise PublicServiceError(409, UNMANAGED_REFUSAL)
                current = await items.members(collection_id)
                scopes = [
                    await self._access.scope(
                        items,
                        part.library_id,
                        part.media_type,
                        criteria_of(part),
                        collection_id=collection_id,
                        smart=rule.smart,
                    )
                    for part in row.libraries
                    if part.criteria is not None
                ]
            await self._refresh_source_summary(rule, row)
            if await self._forget_gone_copies(row):
                async with self._access.database.read_session() as session:
                    current = await CollectionItemRepository(session).members(
                        collection_id
                    )
            await self._take_over_copies(row)
            # Read before the sync retires the libraries it leaves.
            library_names = await self._access.library_names(row.library_ids)
            error = None
            try:
                result = await self._apply(row, rule, policy, current, scopes)
                result.library_names = library_names
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                async with self._access.database.write_session() as session:
                    saved = await CollectionRepository(session).rule(collection_id)
                    if saved is not None:
                        saved.last_synced_at = utc_now()
                        saved.last_error = error
                        session.add(saved)
                await self._access.updated(collection_id)
            # A skipped server copy still lacks the changes; a collection
            # without one is withheld until it is active or large enough.
            if not result.skipped or not row.copies:
                await self._mark_synced(collection_id)
        if not result.skipped and not result.withheld:
            await self._post_sync.run(collection_id)
        return result

    async def _apply(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[CollectionItem],
        scopes: list[LibraryScope],
    ) -> SyncOutcome:
        """Withhold a collection its set or season leaves out, else sync it."""
        start = row.active_start_mmdd or policy.active_start_mmdd
        end = row.active_end_mmdd or policy.active_end_mmdd
        inactive = not self._access.active(start, end)
        if inactive and not policy.delete_when_inactive and not row.deselected:
            return SyncOutcome(
                skipped=True,
                held_back=f"out of season, as it runs {start} to {end}; "
                "left on the servers as it is",
            )
        outcome = SyncOutcome()
        outcome.deleted(
            await self._editor.retire_libraries(row),
            "the collection no longer spans that library",
        )
        if row.deselected or inactive:
            reason = (
                "its group's set no longer selects it"
                if row.deselected
                else f"out of season, as it runs {start} to {end}"
            )
            return await self._withhold(row, outcome, reason)
        if row.kind is CollectionKind.SEPARATOR:
            return await self._sync_separator(row, rule, outcome)
        if rule.smart:
            return await self._sync_smart(row, rule, policy, scopes, outcome)
        return await self._sync_regular(row, rule, policy, current, scopes, outcome)

    async def _withhold(
        self, row: MediaCollection, outcome: SyncOutcome, reason: str
    ) -> SyncOutcome:
        """Take the collection off every server for *reason*, keeping it in Overture."""
        outcome.withheld = True
        if row.copies:
            outcome.deleted(await self._editor.withhold_locked(row), reason)
        else:
            outcome.held_back = f"kept off the servers: {reason}"
        return outcome

    async def _sync_separator(
        self, row: MediaCollection, rule: CollectionRule, outcome: SyncOutcome
    ) -> SyncOutcome:
        """Keep an empty copy in each library, whatever the minimum."""
        for copy in self._access.copies(row):
            created = copy.server_item_id is None
            if created:
                lead = copy.lead
                server = await self._access.provider(copy.server_id).create_collection(
                    lead.library_id, row.title, lead.media_type, []
                )
                copy.place(server.id, server.path)
            outcome.changes.append(
                CopyChange(
                    copy.server_id,
                    tuple(part.library_id for part in copy.libraries),
                    created=created,
                )
            )
        await self._save_placement(row)
        await self._editor.update_locked(row, saved_options(row, rule), push=True)
        return outcome

    async def _sync_smart(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        scopes: list[LibraryScope],
        outcome: SyncOutcome,
    ) -> SyncOutcome:
        """Have Plex evaluate its copies; Overture evaluates other servers' copies.

        Only Plex keeps smart collections, so on another server the collection
        is a regular one holding what the same criteria select.
        """
        await self._editor.replace_kind(row, smart=True)
        by_library = {scope.library_id: scope for scope in scopes}
        copies = self._access.copies(row)
        smart = [copy for copy in copies if self._access.plex(copy.lead.library_id)]
        regular = [copy for copy in copies if copy not in smart]
        members: list[Held] = []
        for copy in smart:
            provider = self._access.provider(copy.server_id)
            lead = copy.lead
            query = await self._membership.smart_query(
                by_library[lead.library_id], policy.order_type, rule.item_limit
            )
            before: set[str] = set()
            target = copy.server_item_id
            created = target is None
            if target is None:
                server = await provider.create_smart_collection(
                    lead.library_id, row.title, lead.media_type, query
                )
                target = server.id
                copy.place(target, server.path)
            else:
                before = set(await provider.get_collection_member_ids(target))
                await provider.update_smart_collection_filter(
                    target, lead.library_id, lead.media_type, query
                )
            held = await provider.get_collection_member_ids(target)
            after = set(held)
            outcome.changes.append(
                CopyChange(
                    copy.server_id,
                    (lead.library_id,),
                    created=created,
                    added=len(after - before),
                    removed=len(before - after),
                    held=len(after),
                )
            )
            members += await self._editor.held(copy.server_id, held)
        if regular:
            libraries = {library for copy in regular for library in copy.library_ids}
            wanted = await self._membership.wanted_in(
                [scope for scope in scopes if scope.library_id in libraries],
                order=policy.order_type,
                limit=rule.item_limit,
            )
            placed, changes = await self._editor.place_members(
                row, regular, wanted, policy.order_type
            )
            members += placed
            outcome.changes += changes
        kind = CollectionKind.SMART if smart else CollectionKind.REGULAR
        await self._editor.store_members(row, members, policy.order_type, kind=kind)
        await self._editor.update_locked(row, saved_options(row, rule), push=True)
        # Labels go unused only when criteria change, which clears the last sync.
        if rule.last_synced_at is None:
            for scope in scopes:
                await self._membership.prune_labels(scope.library_id, scope.media_type)
        return outcome

    async def _sync_regular(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[CollectionItem],
        scopes: list[LibraryScope],
        outcome: SyncOutcome,
    ) -> SyncOutcome:
        was_smart = row.kind is CollectionKind.SMART
        wanted = await self._membership.wanted_in(
            scopes, order=policy.order_type, limit=rule.item_limit
        )
        append = policy.sync_mode is SyncMode.APPEND and not was_smart
        if append and row.unsynced:
            # Members chosen in Overture since the last sync replace the server's.
            chosen = {item.id for items in wanted.values() for item in items}
            for item in current:
                if item.id not in chosen and item.library_id in wanted:
                    wanted[item.library_id].append(item)
            append = False
        member_count = await self._member_count(row, wanted, append=append)
        if member_count < policy.minimum_items:
            below = (
                f"{member_count} of the {policy.minimum_items} titles its minimum needs"
            )
            if policy.delete_below_minimum and row.copies:
                return await self._withhold(row, outcome, below)
            outcome.skipped = True
            outcome.held_back = f"{below}; " + (
                "left on the servers as it is" if row.copies else "not created"
            )
            return outcome
        await self._editor.replace_kind(row, smart=False)
        await self._save_placement(row)
        outcome.changes += await self._editor.set_members_locked(
            row, wanted, policy.order_type, append=append
        )
        await self._editor.update_locked(row, saved_options(row, rule), push=True)
        if was_smart:
            for scope in scopes:
                await self._membership.prune_labels(scope.library_id, scope.media_type)
        return outcome

    async def _member_count(
        self,
        row: MediaCollection,
        wanted: Mapping[str, list[CollectionItem]],
        *,
        append: bool,
    ) -> int:
        """How many titles the sync leaves; append keeps what the servers hold."""
        chosen: set[Held] = {item.id for items in wanted.values() for item in items}
        if not append:
            return len(chosen)
        kept: set[Held] = set()
        for server_id, server_item_id in copy_keys(row.copies):
            if not self._access.configured(server_id):
                continue
            held = await self._access.provider(server_id).get_collection_member_ids(
                server_item_id
            )
            kept.update(await self._editor.held(server_id, held))
        return len(kept | chosen)

    async def _save_placement(self, row: MediaCollection) -> None:
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0)
            save_placement(saved, row)
            place_collection(saved, self._access.provider_registry)
            session.add(saved)

    async def _refresh_source_summary(
        self, rule: CollectionRule, row: MediaCollection
    ) -> None:
        """Keep the summary of the rule's first list current for templates.

        A lookup that fails keeps the last summary rather than failing the sync.
        """
        try:
            summary = await self._sources.summary(library_criteria(row))
        except Exception as exc:  # noqa: BLE001 -- a summary lookup must not fail the sync
            logger.debug("Source summary failed: %s", exc)
            return
        if summary == rule.source_summary:
            return
        rule.source_summary = summary
        async with self._access.database.write_session() as session:
            saved = await CollectionRepository(session).rule(rule.collection_id)
            if saved is not None:
                saved.source_summary = summary
                session.add(saved)

    async def _forget_gone_copies(self, row: MediaCollection) -> bool:
        """Forget the copies deleted on their server, so this sync makes them anew.

        A server sync forgets them too, but a collection's own sync may come
        first. Returns whether any were gone.
        """
        gone = {
            (server_id, server_item_id)
            for server_id, server_item_id in copy_keys(row.copies)
            if self._access.configured(server_id)
            and not await self._access.provider(server_id).has_collection(
                server_item_id
            )
        }
        if not gone:
            return False
        async with self._access.database.write_session() as session:
            saved = await CollectionRepository(session).clear_server_copies(
                row.id or 0, utc_now(), gone
            )
            if saved is not None:
                place_collection(saved, self._access.provider_registry)
                session.add(saved)
        for part in row.libraries:
            if (part.server_id, part.server_item_id or "") in gone:
                part.server_item_id = None
                part.server_path = None
        return True

    async def _take_over_copies(self, row: MediaCollection) -> None:
        """Hold, where the collection has no copy, the server's one of it.

        A server keeps the collections Overture made on it, such as before it
        left MEDIA_SERVERS, and a title names one collection in a library.
        Jellyfin and Emby also make a collection for each TMDB franchise
        themselves, under their own name for it. The unmanaged collection the
        last sync listed with the title or franchise goes, so the server has
        one collection, and the sync sends it this one's choices.
        """
        waiting = {part.library_id for part in row.libraries if not part.server_item_id}
        if not waiting:
            return
        title = row.title.casefold()
        franchise = row.tmdb_collection_id
        async with self._access.database.read_session() as session:
            others = [
                other
                for other in await CollectionRepository(session).list_listed()
                if other.rule is None
                and (
                    other.title.casefold() == title
                    or (franchise is not None and other.tmdb_collection_id == franchise)
                )
                and not waiting.isdisjoint(other.library_ids)
            ]
        for other in others:
            async with (
                self._access.asset_locks.acquire(f"collection:{other.id}"),
                self._access.database.write_session() as session,
            ):
                saved = await self._access.require(session, row.id or 0)
                held = {
                    part.library_id: (part.server_item_id, part.server_path)
                    for part in other.libraries
                    if part.library_id in waiting and part.server_item_id
                }
                for part in saved.libraries:
                    if part.library_id in held:
                        part.server_item_id, part.server_path = held[part.library_id]
                place_collection(saved, self._access.provider_registry)
                session.add(saved)
                await CollectionRepository(session).delete_ids([other.id or 0])
                save_placement(row, saved)
            waiting -= set(other.library_ids)

    async def _mark_synced(self, collection_id: int) -> None:
        async with self._access.database.write_session() as session:
            current = await CollectionRepository(session).get(collection_id)
            if current is not None and current.unsynced:
                current.unsynced = False
                session.add(current)
