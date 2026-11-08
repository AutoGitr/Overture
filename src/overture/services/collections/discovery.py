"""What criteria the media server can evaluate, and what they select now."""

lazy from collections import Counter

lazy from ...config import Settings
lazy from ...domain import (
    CollectionOrder,
    FilterField,
    MediaType,
    SetDimension,
    TmdbChart,
)
lazy from ...integrations.tmdb import chart_available
lazy from ...schemas.collections import (
    CollectionCapabilities,
    CollectionDimensionRead,
    CollectionFieldRead,
    CollectionFieldValue,
    CollectionKindRequest,
    CollectionLibraryPreview,
    CollectionPreview,
    CollectionPreviewRequest,
    CollectionRuleWrite,
    CollectionSourceRead,
    KindRecommendation,
    MdblistListRead,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess, LibraryScope
lazy from .criteria import field_value
lazy from .fields import (
    DIMENSIONS,
    FIELDS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
    field_operators,
    plex_tests,
    smart_only_dimension,
)
lazy from .membership import Membership
lazy from .recommend import recommend_kind
lazy from .sources import SOURCE_LABELS, SourceResolver, selects_media
lazy from .validation import CollectionValidator

#: How many members a preview names.
_PREVIEW_MEMBERS = 20


def _by_label(
    option: CollectionFieldRead | CollectionSourceRead | CollectionDimensionRead,
) -> str:
    """Dropdowns list options alphabetically within their group."""
    return option.label.casefold()


class CollectionDiscovery:
    """Describe the fields, sources and sets on offer, and preview criteria."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        validator: CollectionValidator,
        membership: Membership,
        sources: SourceResolver,
        app_config: Settings,
    ) -> None:
        self._access = access
        self._validator = validator
        self._membership = membership
        self._sources = sources
        self._app_config = app_config

    def capabilities(self, media_type: MediaType) -> CollectionCapabilities:
        """Describe the fields, sources, orders and sets the server supports."""
        server = self._access.server_type
        plex = self._access.plex
        tmdb = self._app_config.tmdb_configured
        return CollectionCapabilities(
            server_type=server,
            spans_libraries=self._access.spans_libraries,
            smart=plex,
            visibility=plex,
            member_labels=plex,
            arr=self._sources.arr(media_type).configured,
            charts=[
                chart
                for chart in TmdbChart
                if tmdb and chart_available(media_type, chart)
            ],
            orders=available_orders(server, media_type, smart=False),
            smart_orders=available_orders(server, media_type, smart=True)
            if plex
            else [],
            fields=sorted(self._fields(media_type), key=_by_label),
            sources=sorted(
                (
                    CollectionSourceRead(
                        type=source,
                        label=label,
                        unavailable=self._sources.unavailable(source, media_type),
                    )
                    for source, label in SOURCE_LABELS.items()
                    # Franchises and Radarr hold only movies, Sonarr only shows.
                    if selects_media(source, media_type)
                ),
                key=_by_label,
            ),
            dimensions=sorted(
                (
                    CollectionDimensionRead(
                        dimension=dimension,
                        label=spec.label,
                        title_format=spec.title_format,
                        smart_only=smart_only_dimension(dimension, server, media_type),
                        strip_prefix=spec.strip_prefix,
                        strip_suffix=spec.strip_suffix,
                        order_type=spec.order_type,
                    )
                    for dimension, spec in DIMENSIONS.items()
                    if dimension_available(dimension, server, media_type, smart=plex)
                    and (
                        tmdb
                        or (
                            dimension is not SetDimension.FRANCHISE
                            and (spec.field is None or not FIELDS[spec.field].tmdb)
                        )
                    )
                ),
                key=_by_label,
            ),
        )

    def _fields(self, media_type: MediaType) -> list[CollectionFieldRead]:
        """The fields collections of the media type can test on the server."""
        server = self._access.server_type
        tmdb = self._app_config.tmdb_configured
        found: list[CollectionFieldRead] = []
        for field, spec in FIELDS.items():
            local = field_available(field, server, media_type, smart=False) and (
                tmdb or not spec.tmdb
            )
            tested = plex_tests(field, server, media_type)
            smart = self._access.plex and (local or tested)
            if not (local or smart):
                continue
            found.append(
                CollectionFieldRead(
                    field=field,
                    label=field_label(field, server),
                    kind=spec.kind,
                    operators=list(field_operators(field, smart=False)),
                    smart_operators=list(field_operators(field, smart=True))
                    if smart
                    else [],
                    local=local,
                    smart=smart,
                    labelled=smart and not tested,
                )
            )
        return found

    async def mdblist_lists(self, query: str) -> list[MdblistListRead]:
        """Find public MDBList lists to name in a source condition."""
        return [
            MdblistListRead(
                id=found.id,
                name=found.name,
                owner=found.user_name,
                items=found.items,
            )
            for found in await self._sources.mdblist_lists(query)
        ]

    async def field_values(
        self,
        media_type: MediaType,
        library_id: str,
        field: FilterField,
        query: str | None = None,
    ) -> list[CollectionFieldValue]:
        """List a field's values in a library, most common first.

        Overture counts what sync stored; fields only Plex knows are listed by
        Plex, without counts. *query* narrows them to values containing it,
        and for TMDB keywords adds those TMDB knows that no title has yet.
        """
        server = self._access.server_type
        counts: Counter[str] = Counter()
        if field_available(field, server, media_type, smart=False):
            items = await self._access.library_items(library_id, media_type)
            collections = (
                await self._access.collection_titles(library_id, None)
                if field is FilterField.COLLECTION
                else {}
            )
            for item in items:
                value = field_value(item, field, collections.get(item.id or 0, ()))
                if isinstance(value, str):
                    counts[value] += 1
                elif isinstance(value, list | tuple):
                    counts.update({str(entry) for entry in value})
        else:
            plex = FIELDS[field].plex
            if (
                not field_available(field, server, media_type, smart=True)
                or plex is None
            ):
                raise PublicServiceError(422, "The media server cannot list this field")
            counts.update(
                dict.fromkeys(
                    (
                        plex.value_of(key, title)
                        for key, title in await self._access.provider().filter_choices(
                            library_id, media_type, plex.key_for(media_type)
                        )
                    ),
                    0,
                )
            )
        typed = (query or "").strip().casefold()
        values = {
            value: count for value, count in counts.items() if typed in value.casefold()
        }
        if typed and field is FilterField.TMDB_KEYWORD:
            known = {value.casefold() for value in values}
            for keyword in await self._sources.tmdb_keywords(typed):
                if keyword.casefold() not in known:
                    known.add(keyword.casefold())
                    values[keyword] = 0
        return [
            CollectionFieldValue(value=value, count=count)
            for value, count in sorted(
                values.items(), key=lambda pair: (-pair[1], pair[0].casefold())
            )
        ]

    async def recommend(self, body: CollectionKindRequest) -> KindRecommendation | None:
        """Return the collection kind that suits a rule, as it is being edited.

        The kind is the collection's, so libraries that disagree give no advice.
        """
        rule = body.rule
        types = await self._access.library_types(e.library_id for e in rule.libraries)
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(session, None, rule)
        advice = [
            recommend_kind(
                library.criteria,
                self.capabilities(types[library.library_id]),
                media_type=types[library.library_id],
                order=policy.order_type,
            )
            for library in rule.libraries
        ]
        first = advice[0]
        return (
            first
            if all(
                entry is not None and first is not None and entry.kind is first.kind
                for entry in advice
            )
            else None
        )

    async def preview(self, body: CollectionPreviewRequest) -> CollectionPreview:
        """What each library's criteria select now."""
        rule = body.rule
        scopes = await self._access.scopes(rule.libraries, body.collection_id)
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(session, None, rule)
        return CollectionPreview(
            libraries=[
                await self._preview_library(scope, rule, policy.order_type)
                for scope in scopes
            ]
        )

    async def _preview_library(
        self, scope: LibraryScope, rule: CollectionRuleWrite, order: CollectionOrder
    ) -> CollectionLibraryPreview:
        """Plex counts a smart collection's members; Overture any other's."""
        library_id, media_type = scope.library_id, scope.media_type
        criteria, items = scope.criteria, scope.items
        self._validator.criteria(media_type, criteria, smart=rule.smart)
        server = self._access.server_type
        local = all(
            field_available(condition.field, server, media_type, smart=False)
            for condition in criteria.field_conditions()
        )
        # Plex answers for a smart collection, so the preview is what it shows;
        # a list only becomes a label Plex can test once the collection is saved.
        if rule.smart and not criteria.source_conditions():
            total, ids = await self._access.provider().find_matching(
                library_id,
                media_type,
                await self._membership.plex_filter(
                    library_id, media_type, criteria, order
                ),
                _PREVIEW_MEMBERS,
            )
            by_server_id = {item.server_item_id: item.title for item in items}
            return CollectionLibraryPreview(
                library_id=library_id,
                member_count=min(total, rule.limit or total),
                members=[by_server_id[i] for i in ids if i in by_server_id],
            )
        if rule.smart and not local:
            raise PublicServiceError(
                422, "Save the collection to preview Plex filters with lists"
            )
        wanted = await self._membership.wanted(
            media_type,
            library_id,
            criteria,
            items,
            order=order,
            limit=rule.limit,
            collection_id=scope.collection_id,
        )
        tests_tmdb = any(
            FIELDS[condition.field].tmdb for condition in criteria.field_conditions()
        )
        return CollectionLibraryPreview(
            library_id=library_id,
            member_count=len(wanted),
            members=[item.title for item in wanted[:_PREVIEW_MEMBERS]],
            tmdb_unread=sum(
                item.tmdb_id is not None and item.tmdb_checked_id != item.tmdb_id
                for item in items
            )
            if tests_tmdb
            else 0,
        )
