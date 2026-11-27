"""Collection groups: their names, shared policy, set and members."""

lazy import logging

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import (
    SEPARATED_SORT_TITLE,
    SMART_CUSTOM_ORDER,
    CollectionKind,
    CollectionOrder,
    MediaType,
)
lazy from ...jobs.progress_log import JobOutcome, LogServer, Report
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.saved_schedules import SavedScheduleRepository
lazy from ...schemas.collections import (
    BulkCollectionOperationResult,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRead,
    CollectionGroupSet,
)
lazy from ...schemas.common import Status, StatusResponse
lazy from ...utils.collection_fields import DIMENSIONS
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..needs import apply_needs
lazy from . import COLLECTIONS_LOCK
lazy from .access import CollectionAccess
lazy from .adoption import CollectionAdoption
lazy from .editor import CollectionEditor
lazy from .rule_sync import RuleSync
lazy from .rules import generator, group_name
lazy from .separators import CollectionSeparators
lazy from .set_runner import CollectionSets
lazy from .validation import CollectionValidator

logger = logging.getLogger(__name__)


async def _logged(
    outcome: JobOutcome,
    target: str,
    reason: str,
    /,
    *,
    count: int = 1,  # noqa: ARG001 -- each value is one collection
    finished: bool = True,  # noqa: ARG001 -- a save tracks no progress
    server: LogServer | None = None,  # noqa: ARG001 -- a set's run touches no server
) -> None:
    """Log what a set's run outside a sync could not save; the sync reports it again."""
    logger.warning("%s: %s %s", target, outcome.value, reason)


class CollectionGroups:
    """Name, configure, sync and remove groups of collections."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        validator: CollectionValidator,
        editor: CollectionEditor,
        adoption: CollectionAdoption,
        sets: CollectionSets,
        rules: RuleSync,
        separators: CollectionSeparators,
    ) -> None:
        self._access = access
        self._validator = validator
        self._editor = editor
        self._adoption = adoption
        self._sets = sets
        self._rules = rules
        self._separators = separators

    async def names(self) -> list[str]:
        """Return the groups' names, as :meth:`list` orders them."""
        return [group.name for group in await self.list()]

    async def rename(self, name: str, replacement: str) -> StatusResponse:
        """Rename a group; its collections hold it by key, so they follow."""
        name, replacement = name.strip(), group_name(replacement)
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
            # Schedules name the groups they run, and keep running this one.
            await SavedScheduleRepository(session).rename_group(group.name, replacement)
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
            PublicServiceError: 422 for a move into itself, or for a group
                holding collections when nothing says what happens to them.
        """
        name = name.strip()
        if body.group is not None and body.group.casefold() == name.casefold():
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
            if rows and body.collections is None:
                raise PublicServiceError(
                    422, "Choose what happens to the group's collections"
                )
            if body.collections in {"orphan", "both"}:
                for row in rows:
                    identity = row.id or 0
                    try:
                        async with self._access.asset_locks.acquire(
                            f"collection:{identity}"
                        ):
                            if body.collections == "orphan":
                                await self._adoption.orphan_locked(
                                    identity, set_removed=True
                                )
                            else:
                                await self._editor.delete_locked(row)
                        result.collection_ids.append(identity)
                    except Exception as exc:  # noqa: BLE001 -- one collection's failure is reported; the rest go on
                        result.errors[identity] = str(exc)
            else:
                result.collection_ids.extend(row.id or 0 for row in rows)
            if not result.errors:
                async with self._access.database.write_session() as session:
                    repo = CollectionRepository(session)
                    group = await repo.group(name)
                    if group is not None:
                        members = await repo.group_members(group)
                        if body.group is not None:
                            moved_to = await repo.ensure_group(body.group)
                            for row in members:
                                row.group = moved_to
                                row.generated_value = None
                                row.updated_at = utc_now()
                                session.add(row)
                            await session.flush()
                            await apply_needs(session, collections=members)
                        await session.delete(group)
        await self._access.changed()
        return result

    async def list(self) -> list[CollectionGroupRead]:
        """Return the groups by name, each with its set."""
        async with self._access.database.read_session() as session:
            rows = {
                group.name: group
                for group in await CollectionRepository(session).groups()
            }
        return [
            CollectionGroupRead(
                name=name,
                set=CollectionGroupSet(
                    dimension=saved.dimension, library_ids=saved.library_ids
                )
                if (saved := generator(rows.get(name))) is not None
                else None,
            )
            for name in sorted(rows, key=lambda name: name.casefold())
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
        A set's collections are made or updated in Overture as it is saved,
        as a collection is; a sync puts them on the servers.

        Raises:
            PublicServiceError: 409 when *new_set* names a group that already
                is a set.
        """
        name = group_name(name)
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            group = await repo.group(name)
            members = await repo.group_members(group) if group else []
            held = {media_type for row in members for media_type in row.media_types}
            libraries = {library for row in members for library in row.library_ids}
        if body.generator is not None:
            held |= set(
                (await self._access.library_types(body.generator.library_ids)).values()
            )
            libraries |= set(body.generator.library_ids)
        # An empty group may come to hold either, on any server, so it offers
        # what each can use.
        self._validator.display(
            body,
            held or tuple(MediaType),
            smart=False,
            servers=self._access.server_types(libraries)
            or self._access.configured_types(),
        )
        if body.generator is not None:
            types = await self._access.library_types(body.generator.library_ids)
            self._validator.smart_set(types, smart=body.generator.smart)
            for library_id, media_type in types.items():
                self._validator.generator(library_id, media_type, body.generator)
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
            # A separator heads its group's collections only while they share
            # its sort title's start, so turning one on gives the group the
            # sort title that keeps them under it, where it can be changed.
            if (
                body.separator
                and body.sort_title_format is None
                and not (row is not None and row.separator)
            ):
                body = body.model_copy(
                    update={"sort_title_format": SEPARATED_SORT_TITLE}
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
        if body.generator is not None:
            await self._sets.run(row, body.generator, _logged)
        await self._access.needs.apply_collections()
        await self._access.changed()
        return body

    async def sync(
        self, name: str, report: Report, *, library_ids: list[str] | None = None
    ) -> None:
        """Run the group's set, if it is one, then sync every collection it holds.

        *library_ids* limits both to what touches those libraries; a set runs
        whole, because a value's collection spans its libraries. Each
        collection's outcome on each server goes to *report*.
        """
        name = name.strip()
        async with self._access.database.read_session() as session:
            group = await CollectionRepository(session).group(name)
        set_generator = generator(group)
        stale: set[int] = set()
        if (
            group is not None
            and set_generator is not None
            and (
                library_ids is None or set(library_ids) & set(set_generator.library_ids)
            )
        ):
            stale = await self._sets.run(group, set_generator, report)
        async with self._access.database.read_session() as session:
            rows = [
                row
                for row in await CollectionRepository(session).list_listed()
                if row.group_name == name
                and (
                    library_ids is None
                    or set(library_ids) & set(row.library_ids)
                    or row.id in stale
                )
            ]
        await report(
            JobOutcome.STARTED,
            f"Group {name}",
            f"syncing its {len(rows)} collection{'' if len(rows) == 1 else 's'}",
            finished=False,
        )
        await self._sync_rows(rows, report)
        try:
            outcome = await self._separators.apply(name)
        except Exception as exc:  # noqa: BLE001 -- a separator's failure is reported; the group's sync stands
            await report(
                JobOutcome.ERROR, f"{name} separator", str(exc), finished=False
            )
            return
        if outcome is not None:
            await outcome.report(
                report, f"{name} separator", servers=self._access.log_server
            )

    async def sync_collections(self, collection_ids: list[int], report: Report) -> None:
        """Sync these collections whole, whatever libraries a run covers."""
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for collection_id in collection_ids
                if (row := await repo.get_listed(collection_id)) is not None
            ]
        await self._sync_rows(rows, report)

    async def _sync_rows(self, rows: list[MediaCollection], report: Report) -> None:
        """Make the servers match each managed collection, reporting each outcome.

        A separator follows its group, which keeps it apart.
        """
        for row in rows:
            if row.rule is None or row.kind is CollectionKind.SEPARATOR:
                continue
            try:
                outcome = await self._rules.sync(row.id or 0)
            except Exception as exc:  # noqa: BLE001 -- one collection's failure is reported; the rest go on
                await report(JobOutcome.ERROR, row.title, str(exc), finished=False)
                continue
            await outcome.report(report, row.title, servers=self._access.log_server)
