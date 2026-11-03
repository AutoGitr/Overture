"""Collection sets: one generated collection per value of a dimension."""

lazy from collections import Counter
lazy from collections.abc import Mapping

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
lazy from .rules import TITLE_TAKEN, criteria, franchise_ids, rule_read
lazy from .sets import SetValue, count_values, set_values
lazy from .sources import SourceResolver
lazy from .validation import CollectionValidator


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
                    await self._access.policy(session, body.media_type, body.group)
                ).minimum_items
            )
            existing = {
                (row.library_id, row.generated_value): row.id
                for row in await CollectionRepository(session).list_listed(
                    body.media_type
                )
                if body.group
                and row.collection_group == body.group
                and row.generated_value is not None
            }
        return [
            CollectionSetEntry(
                library_id=library_id,
                value=value.value,
                title=value.title,
                member_count=value.count,
                below_minimum=below,
                collection_id=existing.get((library_id, value.value)),
            )
            for library_id in body.generator.library_ids
            for value, below in await self._values(
                body.media_type, body.generator, library_id, body.group, minimum
            )
        ]

    async def run(
        self,
        group: CollectionGroup,
        generator: CollectionGenerator,
        result: CollectionGroupSyncResult,
    ) -> None:
        """Create the set's new collections, update the rest and remove stale ones.

        Values below the minimum go when the policy deletes them, and so do
        values the library no longer holds or the set no longer selects.
        """
        media_type = group.media_type
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(session, media_type, group.name)
            listed = [
                row
                for row in await CollectionRepository(session).list_listed(media_type)
                if row.server_type is server
            ]
            rules = {
                rule.collection_id: rule
                for rule in await CollectionRepository(session).rules()
            }
        for library_id in generator.library_ids:
            in_library = [row for row in listed if row.library_id == library_id]
            members = {
                row.generated_value: row
                for row in in_library
                if row.collection_group == group.name
                and row.generated_value is not None
            }
            titles = {
                row.title.casefold()
                for row in in_library
                if row.generated_value is None or row.collection_group != group.name
            }
            # A value the set no longer selects has no members, so it is below minimum.
            stale: set[str] = set(members) if policy.delete_below_minimum else set()
            for value, below in await self._values(
                media_type, generator, library_id, group.name, policy.minimum_items
            ):
                stale.discard(value.value)
                if below:
                    if policy.delete_below_minimum and value.value in members:
                        stale.add(value.value)
                    continue
                await self._apply_value(
                    group, generator, library_id, value, members, titles, rules, result
                )
            for value in sorted(stale):
                row = members[value]
                try:
                    await self._editor.delete(row.id or 0, media_type)
                    result.removed.append(row.id or 0)
                except Exception as exc:
                    result.errors[row.title] = str(exc)
        async with self._access.database.write_session() as session:
            saved = await CollectionRepository(session).group_policy(
                group.server_type, media_type, group.name
            )
            if saved is not None:
                saved.generated_at = utc_now()
                session.add(saved)
        await self._access.changed()

    async def _values(
        self,
        media_type: MediaType,
        generator: CollectionGeneratorBase,
        library_id: str,
        group: str | None,
        minimum: int,
    ) -> list[tuple[SetValue, bool]]:
        """The set's values in one library, and whether each is below the minimum.

        Franchises below the minimum, or kept by collections outside the group,
        are left out rather than looked up on TMDB. Values only Plex knows are
        counted by Plex.
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
                FilterGroup(
                    groups=[
                        generator.criteria,
                        *(value.criteria for value in generator.custom_values),
                    ]
                ),
                items,
            )
            counts = count_values(generator, items, context)
        names: dict[str, str] = {}
        if generator.dimension is SetDimension.FRANCHISE:
            elsewhere = await self._franchises_elsewhere(media_type, group)
            for value, count in list(counts.items()):
                name = (
                    await self._sources.franchise_name(int(value))
                    if count >= minimum and int(value) not in elsewhere
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
                title
                for _, title in await provider.filter_choices(
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

    async def _franchises_elsewhere(
        self, media_type: MediaType, group: str | None
    ) -> set[int]:
        """TMDB franchises collections outside the group already hold."""
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            outside = {
                row.id: row
                for row in await repo.list_listed(media_type)
                if row.collection_group != group and row.server_type is server
            }
            rules = await repo.rules()
        return {
            row.tmdb_collection_id
            for row in outside.values()
            if row.tmdb_collection_id is not None
        } | {
            franchise
            for rule in rules
            if rule.collection_id in outside
            for franchise in franchise_ids(criteria(rule))
        }

    async def _apply_value(
        self,
        group: CollectionGroup,
        generator: CollectionGenerator,
        library_id: str,
        value: SetValue,
        members: Mapping[str, MediaCollection],
        titles: set[str],
        rules: Mapping[int, CollectionRule],
        result: CollectionGroupSyncResult,
    ) -> None:
        """Create the value's collection, or bring the existing one up to date."""
        rule = CollectionRuleWrite(criteria=value.criteria, smart=generator.smart)
        try:
            row = members.get(value.value)
            if row is not None:
                await self._refresh(row, rules.get(row.id or 0), value, rule)
                return
            if value.title.casefold() in titles:
                raise PublicServiceError(409, TITLE_TAKEN)
            detail = await self._editor.create(
                CollectionCreate(
                    title=value.title,
                    media_type=group.media_type,
                    library_id=library_id,
                    collection_group=group.name,
                    rule=rule,
                ),
                generated_value=value.value,
            )
            result.created.append(detail.id)
            titles.add(value.title.casefold())
            await self._post_sync.run(detail.id, group.media_type)
        except Exception as exc:
            result.errors[value.title] = str(exc)

    async def _refresh(
        self,
        row: MediaCollection,
        saved: CollectionRule | None,
        value: SetValue,
        rule: CollectionRuleWrite,
    ) -> None:
        """Bring a set's collection in line with the set's current definition."""
        async with self._access.locked(row.id or 0):
            if row.title != value.title:
                await self._editor.update_locked(
                    row,
                    saved_options(row, saved).model_copy(update={"title": value.title}),
                )
            current = rule_read(saved)
            if (
                current is None
                or current.criteria != rule.criteria
                or current.smart != rule.smart
            ):
                overrides = (
                    current.model_dump(exclude={"criteria", "smart", "limit"})
                    if current
                    else {}
                )
                overrides.pop("last_synced_at", None)
                overrides.pop("last_error", None)
                await self._editor.save_rule_locked(
                    row, rule.model_copy(update=overrides)
                )
