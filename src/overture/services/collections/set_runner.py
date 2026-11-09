"""Collection sets: one generated collection per value of a dimension."""

lazy from collections import Counter
lazy from collections.abc import Collection, Mapping
lazy from dataclasses import dataclass

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import FilterOperator, MediaType, SetDimension
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    CollectionCreate,
    CollectionGenerator,
    CollectionGeneratorBase,
    CollectionGroupSyncResult,
    CollectionLibraryCriteria,
    CollectionRuleWrite,
    CollectionSetEntry,
    CollectionSetPreview,
    FieldCondition,
    FilterGroup,
)
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from .access import CollectionAccess
lazy from .display import saved_options
lazy from .editor import CollectionEditor
lazy from .fields import DIMENSIONS, FIELDS, smart_only_dimension
lazy from .membership import Membership
lazy from .post_sync import PostSync
lazy from .rules import TITLE_TAKEN, franchise_ids, library_criteria, rule_read
lazy from .sets import SetValue, count_values, set_values
lazy from .sources import SourceResolver
lazy from .validation import CollectionValidator


@dataclass(slots=True)
class _SetCollection:
    """One value of a set across its libraries: the collection it makes."""

    title: str
    libraries: list[CollectionLibraryCriteria]
    count: int


class CollectionSets:
    """Preview and run a group's set, creating, refreshing and removing its members."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        validator: CollectionValidator,
        membership: Membership,
        editor: CollectionEditor,
        post_sync: PostSync,
        sources: SourceResolver,
    ) -> None:
        self._access = access
        self._validator = validator
        self._membership = membership
        self._editor = editor
        self._post_sync = post_sync
        self._sources = sources

    async def preview(self, body: CollectionSetPreview) -> list[CollectionSetEntry]:
        """Preview a set's collections in each library, saving nothing."""
        async with self._access.database.read_session() as session:
            minimum = (
                body.minimum_items
                or (
                    await self._access.policy(
                        session, await self._access.group(session, body.group)
                    )
                ).minimum_items
            )
            listed = [
                row
                for row in await CollectionRepository(session).list_listed()
                if row.server_type is self._access.server_type
            ]
        existing = {
            row.generated_value: row.id
            for row in listed
            if body.group
            and row.group_name == body.group
            and row.generated_value is not None
        }
        taken = {
            (library_id, row.title.casefold()): row.id
            for row in listed
            if row.generated_value is None or row.group_name != body.group
            for library_id in row.library_ids
        }
        types = await self._access.library_types(body.generator.library_ids)
        return [
            CollectionSetEntry(
                library_id=library_id,
                value=value.value,
                title=value.title,
                member_count=value.count,
                below_minimum=below,
                collection_id=existing.get(value.value),
                title_taken_by=None
                if value.value in existing
                else taken.get((library_id, value.title.casefold())),
            )
            for library_id, media_type in types.items()
            for value, below in await self._values(
                media_type,
                body.generator,
                library_id,
                body.group,
                minimum,
                set(existing),
            )
        ]

    async def run(
        self,
        group: CollectionGroup,
        generator: CollectionGenerator,
        result: CollectionGroupSyncResult,
    ) -> None:
        """Create the set's new collections, update the rest and deselect stale ones.

        A value makes one collection across every library that holds it. A
        value no library holds, or the set does not select, is
        deselected: its collection leaves the server until the set selects it
        again. Values below the minimum are left to the minimum policy, applied
        when each collection syncs. Overture keeps every collection until it
        is deleted explicitly.
        """
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(session, group)
            listed = [
                row
                for row in await CollectionRepository(session).list_listed()
                if row.server_type is server
            ]
            rules = {
                row.id: row.rule
                for row in listed
                if row.id is not None and row.rule is not None
            }
        members = {
            row.generated_value: row
            for row in listed
            if row.group_id == group.id and row.generated_value is not None
        }
        titles = {
            (library_id, row.title.casefold())
            for row in listed
            if row.generated_value is None or row.group_id != group.id
            for library_id in row.library_ids
        }
        types = await self._access.library_types(generator.library_ids)
        selected: dict[str, _SetCollection] = {}
        for library_id, media_type in types.items():
            for value, _ in await self._values(
                media_type,
                generator,
                library_id,
                group.name,
                policy.minimum_items,
                set(members),
            ):
                found = selected.setdefault(
                    value.value, _SetCollection(value.title, [], 0)
                )
                found.libraries.append(
                    CollectionLibraryCriteria(
                        library_id=library_id, criteria=value.criteria
                    )
                )
                found.count += value.count
        await self._deselect(
            [row for value, row in members.items() if value not in selected],
            [row for value, row in members.items() if value in selected],
        )
        for value, collection in selected.items():
            # An existing collection below the minimum is the minimum
            # policy's to withhold or keep when it syncs.
            if collection.count >= policy.minimum_items or value in members:
                await self._apply_value(
                    group, generator, value, collection, members, titles, rules, result
                )
        for value in sorted(set(members) - set(selected)):
            row = members[value]
            if not row.server_ids:
                continue
            try:
                await self._editor.withhold(row.id or 0)
                result.withheld.append(row.id or 0)
            except Exception as exc:
                result.errors[row.title] = str(exc)
        async with self._access.database.write_session() as session:
            saved = await session.get(CollectionGroup, group.id)
            if saved is not None:
                saved.generated_at = utc_now()
                session.add(saved)
        await self._access.changed()

    async def _deselect(
        self, stale: list[MediaCollection], selected: list[MediaCollection]
    ) -> None:
        """Record which of the set's collections its values still select."""
        changed = {
            row.id or 0: deselected
            for rows, deselected in ((stale, True), (selected, False))
            for row in rows
            if row.deselected is not deselected
        }
        if not changed:
            return
        async with self._access.database.write_session() as session:
            repo = CollectionRepository(session)
            for collection_id, deselected in changed.items():
                row = await repo.get(collection_id)
                if row is not None:
                    row.deselected = deselected
                    session.add(row)

    async def _values(
        self,
        media_type: MediaType,
        generator: CollectionGeneratorBase,
        library_id: str,
        group: str | None,
        minimum: int,
        existing: Collection[str],
    ) -> list[tuple[SetValue, bool]]:
        """The set's values in one library, and whether each is below the minimum.

        Franchises kept by collections outside the group, and new ones below
        the minimum, are left out rather than looked up on TMDB; a franchise
        with a collection in *existing* stays, for the minimum policy to
        decide. Values only Plex knows are counted by Plex.
        """
        self._validator.generator(media_type, generator)
        server = self._access.server_type
        if smart_only_dimension(generator.dimension, server, media_type):
            counts = await self._plex_counts(media_type, generator, library_id)
        else:
            items = await self._access.library_items(library_id, media_type)
            context, _ = await self._membership.context(
                media_type,
                library_id,
                [
                    generator.criteria,
                    *(value.criteria for value in generator.custom_values),
                ],
                items,
                collection_id=None,
            )
            counts = count_values(generator, items, context)
        names: dict[str, str] = {}
        if generator.dimension is SetDimension.FRANCHISE:
            elsewhere = await self._franchises_elsewhere(group)
            for value, count in list(counts.items()):
                name = (
                    await self._sources.franchise_name(int(value))
                    if (count >= minimum or value in existing)
                    and int(value) not in elsewhere
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
        provider = self._access.provider()
        titles = sorted(
            {
                plex.value_of(key, title)
                for key, title in await provider.filter_choices(
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
                await self._membership.plex_filter(library_id, media_type, criteria),
                0,
            )
            counts[title] = total
        return counts

    async def _franchises_elsewhere(self, group: str | None) -> set[int]:
        """TMDB franchises collections outside the group already hold."""
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            outside = [
                row
                for row in await repo.list_listed()
                if row.group_name != group and row.server_type is server
            ]
        return {
            row.tmdb_collection_id
            for row in outside
            if row.tmdb_collection_id is not None
        } | {
            franchise
            for row in outside
            for franchise in franchise_ids(library_criteria(row))
        }

    async def _apply_value(
        self,
        group: CollectionGroup,
        generator: CollectionGenerator,
        value: str,
        collection: _SetCollection,
        members: Mapping[str, MediaCollection],
        titles: set[tuple[str, str]],
        rules: Mapping[int, CollectionRule],
        result: CollectionGroupSyncResult,
    ) -> None:
        """Create the value's collection, or bring the existing one up to date."""
        rule = CollectionRuleWrite(
            libraries=collection.libraries, smart=generator.smart
        )
        title = collection.title.casefold()
        library_ids = [entry.library_id for entry in collection.libraries]
        try:
            row = members.get(value)
            if row is not None:
                await self._refresh(row, rules.get(row.id or 0), collection, rule)
                return
            if any((library_id, title) in titles for library_id in library_ids):
                raise PublicServiceError(409, TITLE_TAKEN)
            detail = await self._editor.create(
                CollectionCreate(
                    title=collection.title, collection_group=group.name, rule=rule
                ),
                generated_value=value,
            )
            result.created.append(detail.id)
            titles.update((library_id, title) for library_id in library_ids)
            await self._post_sync.run(detail.id)
        except Exception as exc:
            result.errors[collection.title] = str(exc)

    async def _refresh(
        self,
        row: MediaCollection,
        saved: CollectionRule | None,
        collection: _SetCollection,
        rule: CollectionRuleWrite,
    ) -> None:
        """Bring a set's collection in line with the set's current definition."""
        async with self._access.locked(row.id or 0):
            if row.title != collection.title:
                await self._editor.update_locked(
                    row,
                    saved_options(row, saved).model_copy(
                        update={"title": collection.title}
                    ),
                )
            current = rule_read(saved, row)
            if (
                current is None
                or current.libraries != rule.libraries
                or current.smart != rule.smart
            ):
                overrides = (
                    current.model_dump(exclude={"libraries", "smart", "limit"})
                    if current
                    else {}
                )
                overrides.pop("last_synced_at", None)
                overrides.pop("last_error", None)
                await self._editor.save_rule_locked(
                    row, rule.model_copy(update=overrides)
                )
