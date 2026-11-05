"""Bringing one managed collection's server copy in line with its rule."""

lazy import logging

lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import UNMANAGED_REFUSAL, CollectionKind, MediaType, SyncMode
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import CollectionSyncResponse
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from .access import CollectionAccess
lazy from .display import saved_options
lazy from .editor import CollectionEditor
lazy from .membership import Membership, stored_ids
lazy from .policy import CollectionPolicy, is_due
lazy from .post_sync import PostSync
lazy from .rules import criteria, rule_read
lazy from .sources import SourceResolver

logger = logging.getLogger(__name__)


class RuleSync:
    """Resolve a rule's members and make them the server collection's."""

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

    async def sync(
        self, collection_id: int, media_type: MediaType, *, scheduled: bool = False
    ) -> CollectionSyncResponse:
        """Resolve every source before changing any server membership."""
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                repo = CollectionRepository(session)
                row = await self._access.require(session, collection_id, media_type)
                rule = await repo.rule(collection_id)
                policy = await self._access.policy(
                    session, media_type, row.collection_group, rule
                )
                current = await repo.members(collection_id)
                library_items = await repo.library_items(
                    media_type, row.library_id or ""
                )
            if rule is None:
                raise PublicServiceError(409, UNMANAGED_REFUSAL)
            if scheduled and not is_due(rule.last_synced_at, policy):
                return CollectionSyncResponse(skipped=True)
            await self._refresh_source_summary(rule)
            error = None
            try:
                result = await self._apply(row, rule, policy, current, library_items)
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
            # without one is now withheld until it is active or large enough.
            if not result.skipped or row.server_item_id is None:
                await self._mark_synced(collection_id)
        if not result.skipped and not result.withheld:
            await self._post_sync.run(collection_id, media_type)
        return result

    async def _apply(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        """Withhold a collection its set or season leaves out, else sync it."""
        inactive = not self._access.active(
            row.active_start_mmdd or policy.active_start_mmdd,
            row.active_end_mmdd or policy.active_end_mmdd,
        )
        if row.deselected or (inactive and policy.delete_when_inactive):
            if row.server_item_id is None:
                return CollectionSyncResponse(withheld=True)
            await self._editor.withhold_locked(row)
            return CollectionSyncResponse(withheld=True, removed=len(current))
        if inactive:
            return CollectionSyncResponse(skipped=True)
        if rule.smart:
            return await self._sync_smart(row, rule, policy, current, library_items)
        return await self._sync_regular(row, rule, policy, current, library_items)

    async def _sync_smart(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        body = rule_read(rule)
        if body is None:
            raise RuntimeError("A smart sync needs its rule")
        provider = self._access.provider()
        await self._editor.replace_kind(row, smart=True)
        query = await self._membership.smart_query(
            row, body, policy.order_type, library_items
        )
        if row.server_item_id is None:
            server = await provider.create_smart_collection(
                row.library_id or "", row.title, row.media_type, query
            )
            row.server_item_id = server.id
            row.server_link = server.server_link
        else:
            await provider.update_smart_collection_filter(
                row.server_item_id, row.library_id or "", row.media_type, query
            )
        row.kind = CollectionKind.SMART
        await self._editor.update_locked(row, saved_options(row, rule))
        remote_ids = await provider.get_collection_member_ids(row.server_item_id)
        members = stored_ids(remote_ids, library_items)
        async with self._access.database.write_session() as session:
            saved = await self._access.require(session, row.id or 0, row.media_type)
            await CollectionRepository(session).replace_members(row.id or 0, members)
            saved.server_item_id = row.server_item_id
            saved.server_link = row.server_link
            saved.kind = CollectionKind.SMART
            saved.child_count = len(remote_ids)
            saved.updated_at = utc_now()
            session.add(saved)
        # Labels go unused only when criteria change, which clears the last sync.
        if rule.last_synced_at is None:
            await self._membership.prune_labels(row.library_id or "", row.media_type)
        old_ids = {item.id or 0 for item in current}
        return CollectionSyncResponse(
            added=len(set(members) - old_ids),
            removed=len(old_ids - set(members)),
        )

    async def _sync_regular(
        self,
        row: MediaCollection,
        rule: CollectionRule,
        policy: CollectionPolicy,
        current: list[MediaItem],
        library_items: list[MediaItem],
    ) -> CollectionSyncResponse:
        was_smart = row.kind is CollectionKind.SMART
        wanted = await self._membership.wanted(
            row.media_type,
            row.library_id or "",
            criteria(rule),
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
            remote_ids = await self._access.provider().get_collection_member_ids(
                row.server_item_id
            )
            member_count = len(
                set(remote_ids) | {item.server_item_id for item in wanted}
            )
        if member_count < policy.minimum_items:
            if policy.delete_below_minimum and row.server_item_id is not None:
                await self._editor.withhold_locked(row)
                return CollectionSyncResponse(withheld=True, removed=len(current))
            return CollectionSyncResponse(skipped=True)
        await self._editor.replace_kind(row, smart=False)
        await self._editor.set_members_locked(
            row, wanted, policy.order_type, append=append
        )
        await self._editor.update_locked(row, saved_options(row, rule))
        if was_smart and row.library_id:
            await self._membership.prune_labels(row.library_id, row.media_type)
        old = {item.id for item in current}
        new = {item.id for item in wanted}
        return CollectionSyncResponse(
            added=len(new - old),
            removed=len(old - new) if not append else 0,
        )

    async def _refresh_source_summary(self, rule: CollectionRule) -> None:
        """Keep the summary of the rule's first list current for templates.

        A lookup that fails keeps the last summary rather than failing the sync.
        """
        try:
            summary = await self._sources.summary(criteria(rule))
        except Exception as exc:
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

    async def _mark_synced(self, collection_id: int) -> None:
        async with self._access.database.write_session() as session:
            current = await CollectionRepository(session).get(collection_id)
            if current is not None and current.unsynced:
                current.unsynced = False
                session.add(current)
