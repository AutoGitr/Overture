"""Which items criteria select, and the labels and queries Plex evaluates them by."""

lazy from collections.abc import Sequence
lazy from itertools import batched

lazy from sqlmodel import col, select

lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import CHUNK_SIZE
lazy from ...domain import (
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    TermKind,
)
lazy from ...repositories.collections import (
    CollectionItem,
    CollectionRepository,
    TermSelection,
)
lazy from ...repositories.terms import TermRepository
lazy from ...schemas.collections import FilterGroup
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from .access import CollectionAccess, LibraryScope
lazy from .criteria import CriteriaContext, evaluate, order_items
lazy from .fields import labelled_field
lazy from .plex_query import choice_keys, compile_plex_query, tag_keys
lazy from .rules import criteria_of
lazy from .sources import (
    SOURCE_LABEL_PREFIX,
    SourceResolver,
    condition_label,
    source_label,
)


def resolve_members(
    ids: list[int], items: list[CollectionItem]
) -> list[CollectionItem]:
    by_id = {item.id: item for item in items}
    if len(set(ids)) != len(ids) or any(item_id not in by_id for item_id in ids):
        raise PublicServiceError(
            422,
            "Members must be distinct active server items in the selected library",
        )
    return [by_id[item_id] for item_id in ids]


def display_order(
    items: list[CollectionItem], order: CollectionOrder
) -> list[CollectionItem]:
    """Show members as the server orders them; stored order is the custom one."""
    if order in {CollectionOrder.CUSTOM, CollectionOrder.RANDOM}:
        return items
    return order_items(items, order)


def stored_ids(server_ids: list[str], items: Sequence[CollectionItem]) -> list[int]:
    """Overture's IDs of the server's items, in the server's order."""
    by_server_id = {item.server_item_id: item for item in items if item.server_item_id}
    return [
        by_server_id[identity].id or 0
        for identity in server_ids
        if identity in by_server_id
    ]


#: The fields that test which other collections hold a title.
_COLLECTION_FIELDS = frozenset({FilterField.COLLECTION, FilterField.IN_COLLECTION})


class Membership:
    """Resolve criteria into members, locally or as a Plex smart filter."""

    def __init__(self, *, access: CollectionAccess, sources: SourceResolver) -> None:
        self._access = access
        self._sources = sources

    async def context(
        self,
        media_type: MediaType,
        library_id: str,
        criteria: Sequence[FilterGroup],
        items: list[CollectionItem],
        *,
        collection_id: int | None,
    ) -> tuple[CriteriaContext, dict[str, list[int]]]:
        """Resolve each source once, and the other collections the criteria test.

        *collection_id* is the collection the criteria select for, if saved.
        """
        resolved: dict[str, list[int]] = {}
        for condition in (
            found for group in criteria for found in group.source_conditions()
        ):
            if condition.key not in resolved:
                resolved[condition.key] = await self._sources.resolve(
                    condition.source,
                    media_type,
                    items,
                    region=await self._access.region(),
                )
        collections = (
            await self._access.collection_titles(library_id, collection_id)
            if any(
                condition.field in _COLLECTION_FIELDS
                for group in criteria
                for condition in group.field_conditions()
            )
            else {}
        )
        context = CriteriaContext(
            sources={key: frozenset(ids) for key, ids in resolved.items()},
            collections=collections,
            now=utc_now(),
        )
        return context, resolved

    async def wanted(
        self,
        media_type: MediaType,
        library_id: str,
        criteria: FilterGroup,
        items: list[CollectionItem],
        *,
        order: CollectionOrder,
        limit: int | None,
        collection_id: int | None,
    ) -> list[CollectionItem]:
        """The members criteria select, ordered, up to the limit.

        A custom order follows the first source the criteria include.
        """
        context, resolved = await self.context(
            media_type, library_id, [criteria], items, collection_id=collection_id
        )
        source_order = next(
            (
                resolved[condition.key]
                for condition in criteria.source_conditions()
                if condition.operator is FilterOperator.IS
            ),
            list[int](),
        )
        return order_items(
            evaluate(items, criteria, context),
            order,
            source_order=source_order,
            limit=limit,
        )

    async def wanted_in(
        self,
        scopes: Sequence[LibraryScope],
        *,
        order: CollectionOrder,
        limit: int | None,
    ) -> dict[str, list[CollectionItem]]:
        """The members each library's criteria select, by library."""
        return {
            scope.library_id: await self.wanted(
                scope.media_type,
                scope.library_id,
                scope.criteria,
                scope.items,
                order=order,
                limit=limit,
                collection_id=scope.collection_id,
            )
            for scope in scopes
        }

    async def sync_label(
        self,
        library_id: str,
        media_type: MediaType,
        label: str,
        wanted_ids: set[int],
        items: list[CollectionItem],
    ) -> None:
        """Put the label on exactly the wanted items, on Plex and locally."""
        folded = label.casefold()
        labeled = {
            item.id
            for item in items
            if any(
                existing.casefold() == folded
                for existing in item.values(TermKind.LABEL)
            )
        }
        by_id = {item.id: item for item in items}
        add = {
            server_id: list(by_id[i].values(TermKind.LABEL))
            for i in wanted_ids - labeled
            if i in by_id and (server_id := by_id[i].server_item_id)
        }
        remove = sorted(
            server_id
            for i in labeled - wanted_ids
            if (server_id := by_id[i].server_item_id)
        )
        if not add and not remove:
            return
        await self._access.provider().sync_item_labels(
            library_id, media_type, label, add=add, remove_ids=remove
        )
        changed = sorted(
            ((wanted_ids - labeled) & by_id.keys()) | (labeled - wanted_ids)
        )
        for batch in batched(changed, CHUNK_SIZE, strict=False):
            async with self._access.database.write_session() as session:
                terms = TermRepository(session)
                held = await terms.values_by_item(batch, TermKind.LABEL)
                stored = await session.exec(
                    select(col(MediaItem.id)).where(col(MediaItem.id).in_(batch))
                )
                await terms.assign_many(
                    {
                        item_id: {
                            TermKind.LABEL: [
                                *(
                                    entry
                                    for entry in held.get(item_id, ())
                                    if entry.casefold() != folded
                                ),
                                *([label] if item_id in wanted_ids else []),
                            ]
                        }
                        for item_id in stored.all()
                        if item_id is not None
                    }
                )

    def labels(self, media_type: MediaType, criteria: FilterGroup) -> dict[str, str]:
        """The label a smart collection tests for each condition Plex cannot.

        Sources and the fields Plex lacks are both kept as labels on the
        items Overture finds them to match.
        """
        server = self._access.server_type
        labels = {
            condition.key: source_label(condition)
            for condition in criteria.source_conditions()
        }
        labels.update(
            {
                condition.key: condition_label(condition)
                for condition in criteria.field_conditions()
                if labelled_field(condition.field, server, media_type)
            }
        )
        return labels

    async def prune_labels(self, library_id: str, media_type: MediaType) -> None:
        """Remove Overture's labels no smart collection in the library filters on."""
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            used = {
                label
                for row in await repo.list_all()
                if row.rule is not None and row.rule.smart
                for part in row.libraries
                if part.library_id == library_id and part.criteria is not None
                for label in self.labels(media_type, criteria_of(part)).values()
            }
            items = await repo.library_items(
                media_type, library_id, TermSelection(frozenset({TermKind.LABEL}))
            )
        stale = {
            label
            for item in items
            for label in item.values(TermKind.LABEL)
            if label.startswith(SOURCE_LABEL_PREFIX) and label not in used
        }
        for label in sorted(stale):
            await self.sync_label(library_id, media_type, label, set(), items)

    async def smart_query(
        self, scope: LibraryScope, order: CollectionOrder, limit: int | None
    ) -> str:
        """Label what Plex cannot test, then compile the query Plex evaluates."""
        library_id, media_type = scope.library_id, scope.media_type
        criteria, items = scope.criteria, scope.items
        labels = self.labels(media_type, criteria)
        if labels:
            context, resolved = await self.context(
                media_type,
                library_id,
                [criteria],
                items,
                collection_id=scope.collection_id,
            )
            fields = {
                condition.key: condition for condition in criteria.field_conditions()
            }
            for key, label in labels.items():
                wanted = (
                    {
                        item.id
                        for item in evaluate(
                            items, FilterGroup(conditions=[fields[key]]), context
                        )
                    }
                    if key in fields
                    else set(resolved[key])
                )
                await self.sync_label(library_id, media_type, label, wanted, items)
        return await self._compile(
            library_id, media_type, criteria, order, limit, labels
        )

    async def plex_filter(
        self,
        library_id: str,
        media_type: MediaType,
        criteria: FilterGroup,
        order: CollectionOrder = CollectionOrder.TITLE_ASC,
    ) -> str:
        """Compile criteria Plex tests itself into the query Plex evaluates."""
        return await self._compile(library_id, media_type, criteria, order, None, {})

    async def _compile(
        self,
        library_id: str,
        media_type: MediaType,
        criteria: FilterGroup,
        order: CollectionOrder,
        limit: int | None,
        labels: dict[str, str],
    ) -> str:
        provider = self._access.provider()
        choices = {
            key: choice_keys(await provider.filter_choices(library_id, media_type, key))
            for key in tag_keys(criteria, media_type, labels)
        }
        return compile_plex_query(
            criteria,
            media_type=media_type,
            order=order,
            limit=limit,
            choices=choices,
            labels=labels,
        )
