"""Collection groups: their names, shared policy, set and members."""

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.media_collection import MediaCollection
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
    CollectionSetSummary,
)
lazy from ...schemas.common import Status, StatusResponse
lazy from ...utils.collection_fields import DIMENSIONS
lazy from ...utils.collection_groups import collection_group
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from . import COLLECTIONS_LOCK
lazy from .access import CollectionAccess
lazy from .editor import CollectionEditor
lazy from .rule_sync import RuleSync
lazy from .rules import generator, group_name
lazy from .separators import CollectionSeparators
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
        separators: CollectionSeparators,
    ) -> None:
        self._access = access
        self._validator = validator
        self._editor = editor
        self._sets = sets
        self._rules = rules
        self._separators = separators

    async def names(self) -> list[str]:
        """Return the groups, Ungrouped always among them."""
        async with self._access.database.read_session() as session:
            groups = await CollectionRepository(session).groups()
        return sorted({UNGROUPED_GROUP} | {group.name for group in groups})

    async def rename(self, name: str, replacement: str) -> StatusResponse:
        """Rename a group; its collections hold it by key, so they follow."""
        name, replacement = name.strip(), group_name(replacement)
        if UNGROUPED_GROUP.casefold() in {name.casefold(), replacement.casefold()}:
            raise PublicServiceError(
                422, "The Ungrouped group cannot be renamed or replaced"
            )
        async with (
            self._access.asset_locks.acquire(COLLECTIONS_LOCK),
            self._access.database.write_session() as session,
        ):
            repo = CollectionRepository(session)
            group = await repo.group(name)
            if group is None:
                raise PublicServiceError(404, "Collection group not found")
            if replacement != name and await repo.group(replacement):
                raise PublicServiceError(
                    409, "A collection group with this name already exists"
                )
            group.name = replacement
            session.add(group)
            await self._separators.refuse_taken(session, group)
            for row in await repo.group_members(group):
                row.updated_at = utc_now()
                session.add(row)
        await self._access.changed()
        return StatusResponse(status=Status.OK)

    async def delete(
        self, name: str, body: CollectionGroupDelete
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
        result = BulkCollectionOperationResult()
        async with self._access.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._access.database.read_session() as session:
                repo = CollectionRepository(session)
                group = await repo.group(name)
                rows = await repo.group_members(group) if group else []
            if group is None:
                raise PublicServiceError(404, "Collection group not found")
            rows = await self._separators.discard(rows)
            if body.collections in {"orphan", "both"}:
                for row in rows:
                    identity = row.id or 0
                    try:
                        async with self._access.asset_locks.acquire(
                            f"collection:{identity}"
                        ):
                            if body.collections == "orphan":
                                await self._editor.orphan_locked(
                                    identity, set_removed=True
                                )
                            else:
                                await self._editor.delete_locked(row)
                        result.collection_ids.append(identity)
                    except Exception as exc:
                        result.errors[identity] = str(exc)
            else:
                result.collection_ids.extend(row.id or 0 for row in rows)
            if not result.errors:
                async with self._access.database.write_session() as session:
                    repo = CollectionRepository(session)
                    group = await repo.group(name)
                    if group is not None:
                        moved_to = await repo.ensure_group(target)
                        for row in await repo.group_members(group):
                            row.group = moved_to
                            row.generated_value = None
                            row.updated_at = utc_now()
                            session.add(row)
                        await session.flush()
                        await session.delete(group)
        await self._access.changed()
        return result

    async def sets(self) -> list[CollectionSetSummary]:
        """Return the groups that are sets, by name."""
        async with self._access.database.read_session() as session:
            policies = await CollectionRepository(session).groups()
        return [
            CollectionSetSummary(
                group=group.name,
                dimension=saved.dimension,
                library_ids=saved.library_ids,
            )
            for group in sorted(policies, key=lambda group: group.name.casefold())
            if (saved := generator(group)) is not None
        ]

    async def policy(self, name: str) -> CollectionGroupPolicy:
        """Return nullable group overrides, including for a new group."""
        async with self._access.database.read_session() as session:
            row = await CollectionRepository(session).group(name.strip())
        if row is None:
            return CollectionGroupPolicy()
        return CollectionGroupPolicy(
            **row.model_dump(
                include=set(CollectionGroupPolicy.model_fields) - {"generator"}
            ),
            generator=generator(row),
        )

    async def save_policy(
        self, name: str, body: CollectionGroupPolicy, *, new_set: bool = False
    ) -> CollectionGroupPolicy:
        """Save group defaults without replacing explicit collection overrides.

        With *new_set*, the body creates a set, which never replaces another.

        Raises:
            PublicServiceError: 409 when *new_set* names a group that already
                is a set.
        """
        name = group_name(name)
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            group = await repo.group(name)
            held = {
                media_type
                for row in (await repo.group_members(group) if group else [])
                for media_type in row.media_types
            }
        if body.generator is not None:
            held |= set(
                (await self._access.library_types(body.generator.library_ids)).values()
            )
        # An empty group may come to hold either, so it offers what both can use.
        self._validator.display(body, held or tuple(MediaType), smart=False)
        if body.generator is not None:
            if name.casefold() == UNGROUPED_GROUP.casefold():
                raise PublicServiceError(
                    422,
                    f"{UNGROUPED_GROUP} holds collections without a group, "
                    "so it cannot be a set",
                )
            types = await self._access.library_types(body.generator.library_ids)
            for media_type in set(types.values()):
                self._validator.generator(media_type, body.generator)
            if body.generator.smart and body.order_type is CollectionOrder.CUSTOM:
                raise PublicServiceError(422, SMART_CUSTOM_ORDER)
        async with (
            self._access.asset_locks.acquire(COLLECTIONS_LOCK),
            self._access.database.write_session() as session,
        ):
            row = await CollectionRepository(session).group(name)
            if new_set and (current := generator(row)) is not None:
                raise PublicServiceError(
                    409,
                    f'"{name}" already splits by '
                    f"{DIMENSIONS[current.dimension].label}; "
                    "edit that set in the group's settings, or name another group",
                )
            if row is None:
                row = CollectionGroup(name=name)
            row.sqlmodel_update(body.model_dump(exclude={"generator"}))
            row.generator = (
                body.generator.model_dump(mode="json")
                if body.generator is not None
                else None
            )
            session.add(row)
            await session.flush()
            await self._separators.refuse_taken(session, row)
        await self._access.changed()
        return body

    async def sync(
        self, name: str, *, library_ids: list[str] | None = None
    ) -> CollectionGroupSyncResult:
        """Run the group's set, if it is one, then sync every collection it holds.

        *library_ids* limits both to what touches those libraries; a set runs
        whole, because a value's collection spans its libraries.
        """
        name = name.strip()
        async with self._access.database.read_session() as session:
            group = await CollectionRepository(session).group(name)
        result = CollectionGroupSyncResult()
        set_generator = generator(group)
        if (
            group is not None
            and set_generator is not None
            and (
                library_ids is None or set(library_ids) & set(set_generator.library_ids)
            )
        ):
            await self._sets.run(group, set_generator, result)
        async with self._access.database.read_session() as session:
            rows = [
                row
                for row in await CollectionRepository(session).list_listed()
                if row.group_name == name
                and (library_ids is None or set(library_ids) & set(row.library_ids))
            ]
        await self._sync_rows(rows, result)
        try:
            await self._separators.apply(name)
        except Exception as exc:
            result.errors[name] = str(exc)
        return result

    async def sync_collections(
        self, collection_ids: list[int]
    ) -> CollectionGroupSyncResult:
        """Sync these collections whole, whatever libraries a run covers."""
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for collection_id in collection_ids
                if (row := await repo.get_listed(collection_id)) is not None
            ]
        result = CollectionGroupSyncResult()
        await self._sync_rows(rows, result)
        return result

    async def _sync_rows(
        self, rows: list[MediaCollection], result: CollectionGroupSyncResult
    ) -> None:
        """Make the server match each managed collection, counting what fails.

        A separator follows its group, which keeps it apart.
        """
        for row in rows:
            if row.rule is None or row.kind is CollectionKind.SEPARATOR:
                continue
            try:
                await self._rules.sync(row.id or 0)
                result.synced += 1
            except Exception as exc:
                result.errors[row.title] = str(exc)
