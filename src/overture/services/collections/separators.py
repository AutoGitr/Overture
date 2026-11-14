"""Separators: empty collections that head their group's collections on Plex."""

lazy from collections.abc import Sequence

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import CollectionKind, MediaType
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import CollectionLibraryCriteria, FilterGroup
lazy from ...utils.collection_formats import format_sort_title, literal_template
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from . import COLLECTIONS_LOCK
lazy from .access import CollectionAccess
lazy from .editor import CollectionEditor
lazy from .rule_sync import RuleSync
lazy from .rules import TITLE_TAKEN, apply_libraries

#: What a separator selects in each library: nothing, as it holds no members.
_NOTHING = FilterGroup()


def _held_libraries(rows: Sequence[MediaCollection]) -> dict[str, MediaType]:
    return {
        part.library_id: part.media_type
        for row in rows
        if row.kind is not CollectionKind.SEPARATOR
        for part in row.libraries
        if part.criteria is not None
    }


class CollectionSeparators:
    """Keep a group's separator as its setting and collections say.

    A separator is titled after its group, spans the libraries the group's
    collections do, holds no members and gets generated art. Its sort title is
    the group's template with an empty title, so a template that puts the
    group first, such as ``{group} {title}``, sorts it right before them.
    Only Plex keeps empty collections, so other servers have none.
    """

    def __init__(
        self, *, access: CollectionAccess, editor: CollectionEditor, rules: RuleSync
    ) -> None:
        self._access = access
        self._editor = editor
        self._rules = rules

    async def apply(self, name: str) -> None:
        """Create, update or remove the separator of the group named *name*.

        Raises:
            PublicServiceError: 409 when another collection in one of its
                libraries already has the group's name.
        """
        async with self._access.asset_locks.acquire(COLLECTIONS_LOCK):
            async with self._access.database.read_session() as session:
                repo = CollectionRepository(session)
                group = await repo.group(name)
                rows = await repo.group_members(group) if group else []
                policy = await self._access.policy(session, group)
                if group is not None:
                    await self.refuse_taken(session, group)
            separator = next(
                (row for row in rows if row.kind is CollectionKind.SEPARATOR), None
            )
            libraries = _held_libraries(rows)
            if (
                group is None
                or not group.separator
                or not self._access.plex
                or not libraries
            ):
                if separator is not None:
                    async with self._access.asset_locks.acquire(
                        f"collection:{separator.id}"
                    ):
                        await self._editor.delete_locked(separator)
                return
            sort_title_format = (
                literal_template(
                    format_sort_title(
                        policy.sort_title_format, title="", group=group.name
                    ).strip()
                )
                if policy.sort_title_format
                else None
            )
            if separator is None:
                collection_id = await self._save(
                    group, None, libraries, sort_title_format
                )
            else:
                async with self._access.asset_locks.acquire(
                    f"collection:{separator.id}"
                ):
                    collection_id = await self._save(
                        group, separator, libraries, sort_title_format
                    )
        await self._rules.sync(collection_id)

    async def refuse_taken(self, session: AsyncSession, group: CollectionGroup) -> None:
        """Refuse a separator whose title a collection in its libraries already has.

        Raises:
            PublicServiceError: 409 when the group's name is taken.
        """
        if not group.separator or not self._access.plex:
            return
        repo = CollectionRepository(session)
        libraries = _held_libraries(await repo.group_members(group))
        if any(
            row.kind is not CollectionKind.SEPARATOR
            and row.title.casefold() == group.name.casefold()
            and not libraries.keys().isdisjoint(row.library_ids)
            for row in await repo.list_listed()
        ):
            raise PublicServiceError(409, TITLE_TAKEN)

    async def discard(self, rows: Sequence[MediaCollection]) -> list[MediaCollection]:
        """Delete the separator among a group's *rows*; return the others.

        A separator heads its own group only, so it never moves to another.
        The caller holds the listing lock.
        """
        kept: list[MediaCollection] = []
        for row in rows:
            if row.kind is CollectionKind.SEPARATOR:
                async with self._access.asset_locks.acquire(f"collection:{row.id}"):
                    await self._editor.delete_locked(row)
            else:
                kept.append(row)
        return kept

    async def _save(
        self,
        group: CollectionGroup,
        separator: MediaCollection | None,
        libraries: dict[str, MediaType],
        sort_title_format: str | None,
    ) -> int:
        """Store the separator as it should be, adding it if missing."""
        async with self._access.database.write_session() as session:
            row = (
                await CollectionRepository(session).get(separator.id or 0)
                if separator is not None
                else None
            )
            created = row is None
            if row is None:
                now = utc_now()
                row = MediaCollection(
                    kind=CollectionKind.SEPARATOR,
                    last_synced_at=now,
                    created_at=now,
                    libraries=[],
                )
                row.group_id = group.id
            row.title = group.name
            row.sort_title_format = sort_title_format
            row.updated_at = utc_now()
            apply_libraries(
                row,
                [
                    CollectionLibraryCriteria(library_id=key, criteria=_NOTHING)
                    for key in libraries
                ],
                libraries,
            )
            session.add(row)
            await session.flush()
            if created:
                session.add(CollectionRule(collection_id=row.id or 0))
            return row.id or 0
