"""Custom filters of the library's titles, tested as collection criteria are.

The server tests each metadata and source condition against what sync stored;
the browser tests library status conditions against the live library list and
combines the results, so status filters follow every change at once.
"""

lazy from ...domain import MediaType
lazy from ...repositories.libraries import LibraryRepository
lazy from ...schemas.collections import (
    CollectionFieldRead,
    CollectionLibraryCriteria,
    FieldCondition,
    FilterGroup,
)
lazy from ...schemas.library_filters import (
    LibraryFilterCapabilities,
    LibraryFilterMatch,
    LibraryFilterMatchRequest,
)
lazy from ...utils.collection_fields import (
    FIELDS,
    field_label,
    field_operators,
    library_field_available,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .criteria import evaluate
lazy from .discovery import CollectionDiscovery
lazy from .membership import Membership
lazy from .validation import CollectionValidator


class LibraryFilters:
    """What custom filters can test, and the titles each condition selects."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        validator: CollectionValidator,
        membership: Membership,
        discovery: CollectionDiscovery,
    ) -> None:
        self._access = access
        self._validator = validator
        self._membership = membership
        self._discovery = discovery

    def capabilities(self, media_type: MediaType) -> LibraryFilterCapabilities:
        """The fields and sources a custom filter of the media type can test.

        A filter tests the titles of every library, so it offers what any
        configured server's titles hold.
        """
        servers = sorted(self._access.configured_types())
        tmdb = self._access.app_config.tmdb_configured
        fields = [
            CollectionFieldRead(
                field=field,
                label=field_label(field, available[0]),
                kind=spec.kind,
                operators=list(field_operators(field, smart=False)),
                smart_operators=[],
                local=True,
                smart=False,
                library_status=spec.library_only,
                choices=list(spec.choices),
            )
            for field, spec in FIELDS.items()
            if (
                available := [
                    server
                    for server in servers
                    if library_field_available(field, server, media_type)
                ]
            )
            and (tmdb or not spec.tmdb)
        ]
        return LibraryFilterCapabilities(
            fields=sorted(fields, key=lambda entry: entry.label.casefold()),
            sources=self._discovery.capabilities(media_type).sources,
        )

    async def match(self, body: LibraryFilterMatchRequest) -> LibraryFilterMatch:
        """The titles of the media type each condition selects, in every library.

        Raises:
            PublicServiceError: 422 for a library status condition, which the
                browser tests, or one the library cannot test.
        """
        media_type = body.media_type
        if any(
            isinstance(condition, FieldCondition)
            and FIELDS[condition.field].library_only
            for condition in body.conditions
        ):
            raise PublicServiceError(
                422, "Library status conditions are tested in the browser"
            )
        combined = FilterGroup(mode="any", conditions=body.conditions)
        self._validator.library_criteria(
            media_type, combined, self._access.configured_types()
        )
        async with self._access.database.read_session() as session:
            library_ids = [
                library.id
                for library in await LibraryRepository(session).listed()
                if library.media_type is media_type
            ]
        # One scope per library loads the values every condition tests at once.
        scopes = await self._access.scopes(
            [
                CollectionLibraryCriteria(library_id=library_id, criteria=combined)
                for library_id in library_ids
            ]
        )
        matched: list[set[int]] = [set() for _ in body.conditions]
        for scope in scopes:
            context, _ = await self._membership.context(
                media_type,
                scope.library_id,
                [combined],
                scope.items,
                collection_id=None,
            )
            for selected, condition in zip(matched, body.conditions, strict=True):
                selected.update(
                    item.id
                    for item in evaluate(
                        scope.items, FilterGroup(conditions=[condition]), context
                    )
                )
        return LibraryFilterMatch(item_ids=[sorted(ids) for ids in matched])
