"""Collection groups: their names, shared policy, set and members."""

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...domain import (
    SMART_CUSTOM_ORDER,
    UNGROUPED_GROUP,
    CollectionKind,
    CollectionOrder,
    MediaType,
)
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    BulkCollectionOperationResult,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupSyncResult,
)
lazy from ...schemas.common import Status, StatusResponse
lazy from ...utils.collection_groups import collection_group
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from . import COLLECTIONS_LOCK
lazy from .access import CollectionAccess
lazy from .display import saved_options
lazy from .editor import CollectionEditor
lazy from .rule_sync import RuleSync
lazy from .rules import generator, group_name
lazy from .set_runner import CollectionSets
lazy from .validation import CollectionValidator


class CollectionGroups:
    """Name, configure, sync and remove groups of collections."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        validator: CollectionValidator,
        editor: CollectionEditor,
        sets: CollectionSets,
        rules: RuleSync,
    ) -> None:
        self._access = access
        self._validator = validator
        self._editor = editor
        self._sets = sets
        self._rules = rules

    async def names(self, media_type: MediaType) -> list[str]:
        """Return the stored groups: those with defaults or managed collections.

        Unmanaged collections belong to no group until they are adopted.
        """
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.server_type is server
            ]
            policies = await repo.group_policies(server, media_type)
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

    async def rename(
        self, media_type: MediaType, name: str, replacement: str
    ) -> StatusResponse:
        """Rename defaults and every member atomically, including unlisted rows."""
        name, replacement = name.strip(), group_name(replacement)
        if UNGROUPED_GROUP.casefold() in {name.casefold(), replacement.casefold()}:
            raise PublicServiceError(
                422, "The Ungrouped group cannot be renamed or replaced"
            )
        server = self._access.server_type
        async with (
            self._access.asset_locks.acquire(COLLECTIONS_LOCK),
            self._access.database.write_session() as session,
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
        await self._access.changed()
        return StatusResponse(status=Status.OK)

    async def delete(
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
        server = self._access.server_type
        result = BulkCollectionOperationResult()
        async with self._access.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._access.database.read_session() as session:
                repo = CollectionRepository(session)
                rows = await repo.group_members(server, media_type, name)
                group = await repo.group_policy(server, media_type, name)
            if group is None and not rows:
                raise PublicServiceError(404, "Collection group not found")
            if body.collections in {"overture", "both"}:
                for row in rows:
                    identity = row.id or 0
                    try:
                        async with self._access.asset_locks.acquire(
                            f"collection:{identity}"
                        ):
                            await self._editor.delete_locked(
                                row, server=body.collections == "both"
                            )
                        result.collection_ids.append(identity)
                    except Exception as exc:
                        result.errors[identity] = str(exc)
            else:
                result.collection_ids.extend(row.id or 0 for row in rows)
            if not result.errors:
                async with self._access.database.write_session() as session:
                    repo = CollectionRepository(session)
                    for row in await repo.group_members(server, media_type, name):
                        row.collection_group = target
                        row.generated_value = None
                        row.updated_at = utc_now()
                        session.add(row)
                    group = await repo.group_policy(server, media_type, name)
                    if group is not None:
                        await session.delete(group)
        await self._access.changed()
        return result

    async def policy(self, media_type: MediaType, name: str) -> CollectionGroupPolicy:
        """Return nullable group overrides, including for a new group."""
        async with self._access.database.read_session() as session:
            row = await CollectionRepository(session).group_policy(
                self._access.server_type, media_type, name.strip()
            )
        if row is None:
            return CollectionGroupPolicy()
        return CollectionGroupPolicy(
            **row.model_dump(
                include=set(CollectionGroupPolicy.model_fields) - {"generator"}
            ),
            generator=generator(row),
        )

    async def save_policy(
        self, media_type: MediaType, name: str, body: CollectionGroupPolicy
    ) -> CollectionGroupPolicy:
        """Save group defaults without replacing explicit collection overrides."""
        name = group_name(name)
        self._validator.display(body, media_type, smart=False)
        if body.generator is not None:
            if name.casefold() == UNGROUPED_GROUP.casefold():
                raise PublicServiceError(
                    422,
                    f"{UNGROUPED_GROUP} holds collections without a group, "
                    "so it cannot be a set",
                )
            self._validator.generator(media_type, body.generator)
            if body.generator.smart and body.order_type is CollectionOrder.CUSTOM:
                raise PublicServiceError(422, SMART_CUSTOM_ORDER)
        server = self._access.server_type
        async with self._access.database.write_session() as session:
            row = await CollectionRepository(session).group_policy(
                server, media_type, name
            )
            if row is None:
                row = CollectionGroup(
                    server_type=server, media_type=media_type, name=name
                )
            row.sqlmodel_update(body.model_dump(exclude={"generator"}))
            row.generator_json = (
                body.generator.model_dump_json() if body.generator is not None else None
            )
            session.add(row)
        await self._access.changed()
        return body

    async def apply_policy(
        self, media_type: MediaType, name: str
    ) -> BulkCollectionOperationResult:
        """Apply display defaults while preserving sources and rule overrides.

        A group may mix regular and smart collections; Plex orders smart ones
        itself, so a custom order skips them.
        """
        server = self._access.server_type
        async with self._access.database.read_session() as session:
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
                async with self._access.locked(collection_id):
                    async with self._access.database.read_session() as session:
                        row = await self._access.require(
                            session, collection_id, media_type
                        )
                        rule = await CollectionRepository(session).rule(collection_id)
                    if row.collection_group != name:
                        continue
                    await self._editor.update_locked(row, saved_options(row, rule))
                result.collection_ids.append(collection_id)
                await self._access.updated(collection_id)
            except Exception as exc:
                result.errors[collection_id] = str(exc)
        return result

    async def sync(self, media_type: MediaType, name: str) -> CollectionGroupSyncResult:
        """Run the group's set, if it is one, then sync its other collections."""
        name = name.strip()
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            group = await CollectionRepository(session).group_policy(
                server, media_type, name
            )
        result = CollectionGroupSyncResult()
        set_generator = generator(group)
        if group is not None and set_generator is not None:
            await self._sets.run(group, set_generator, result)
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.server_type is server and row.collection_group == name
            ]
            managed = {rule.collection_id for rule in await repo.rules()}
        for row in rows:
            if row.id in managed and row.id not in result.created:
                try:
                    await self._rules.sync(row.id or 0, media_type)
                    result.synced += 1
                except Exception as exc:
                    result.errors[row.title] = str(exc)
        return result
