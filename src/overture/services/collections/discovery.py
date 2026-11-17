"""What criteria the media server can evaluate, and what they select."""

lazy from collections import Counter
lazy from collections.abc import Iterable, Sequence

lazy from ...config import Settings
lazy from ...domain import (
    CollectionOrder,
    FilterField,
    MediaType,
    ServerType,
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
lazy from ...utils.collection_fields import (
    DIMENSIONS,
    FIELDS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
    field_operators,
    labelled_field,
    plex_tests,
    smart_only_dimension,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess, LibraryScope
lazy from .criteria import TERM_FIELDS, field_value
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


def _union(orders: Iterable[Sequence[CollectionOrder]]) -> list[CollectionOrder]:
    """Every order any of the lists offers, in the order orders are declared."""
    offered = {order for listed in orders for order in listed}
    return [order for order in CollectionOrder if order in offered]


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

    def capabilities(
        self, media_type: MediaType, library_ids: Sequence[str] | None = None
    ) -> CollectionCapabilities:
        """Describe what collections of these libraries can do on their servers.

        Without libraries it describes every configured server. A collection
        spanning several servers is offered what any of them supports; the
        others fall back to their nearest.
        """
        servers = sorted(
            self._access.server_types(library_ids)
            if library_ids
            else self._access.configured_types()
        )
        plex = ServerType.PLEX in servers
        tmdb = self._app_config.tmdb_configured
        return CollectionCapabilities(
            server_types=servers,
            spans_libraries=all(
                self._access.spans_libraries(server) for server in servers
            ),
            smart=plex,
            visibility=plex,
            member_labels=plex,
            arr=self._sources.arr(media_type).configured,
            charts=[
                chart
                for chart in TmdbChart
                if tmdb and chart_available(media_type, chart)
            ],
            orders=_union(
                available_orders(server, media_type, smart=False) for server in servers
            ),
            smart_orders=available_orders(ServerType.PLEX, media_type, smart=True)
            if plex
            else [],
            fields=sorted(self._fields(media_type, servers), key=_by_label),
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
                        smart_only=all(
                            smart_only_dimension(dimension, server, media_type)
                            for server in servers
                        ),
                        strip_prefix=spec.strip_prefix,
                        strip_suffix=spec.strip_suffix,
                        order_type=spec.order_type,
                    )
                    for dimension, spec in DIMENSIONS.items()
                    if any(
                        dimension_available(
                            dimension,
                            server,
                            media_type,
                            smart=server is ServerType.PLEX,
                        )
                        for server in servers
                    )
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

    def _fields(
        self, media_type: MediaType, servers: Sequence[ServerType]
    ) -> list[CollectionFieldRead]:
        """The fields collections of the media type can test on any of *servers*."""
        tmdb = self._app_config.tmdb_configured
        found: list[CollectionFieldRead] = []
        for field, spec in FIELDS.items():
            local_on = [
                server
                for server in servers
                if field_available(field, server, media_type, smart=False)
                and (tmdb or not spec.tmdb)
            ]
            tested = ServerType.PLEX in servers and plex_tests(
                field, ServerType.PLEX, media_type
            )
            smart = ServerType.PLEX in servers and (
                ServerType.PLEX in local_on or tested
            )
            if not (local_on or smart):
                continue
            found.append(
                CollectionFieldRead(
                    field=field,
                    label=field_label(field, next(iter(local_on or servers))),
                    kind=spec.kind,
                    operators=list(field_operators(field, smart=False)),
                    smart_operators=list(field_operators(field, smart=True))
                    if smart
                    else [],
                    local=bool(local_on),
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
        server = self._access.server_type(library_id)
        counts: Counter[str] = Counter()
        if field_available(field, server, media_type, smart=False):
            if (kind := TERM_FIELDS.get(field)) is not None:
                counts.update(
                    await self._access.term_counts(library_id, media_type, kind)
                )
            else:
                items = await self._access.library_items(library_id, media_type)
                collections = (
                    await self._access.collection_titles(library_id, None)
                    if field is FilterField.COLLECTION
                    else {}
                )
                for item in items:
                    value = field_value(item, field, collections.get(item.id, ()))
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
            provider = self._access.library_provider(library_id)
            counts.update(
                dict.fromkeys(
                    (
                        plex.value_of(key, title)
                        for key, title in await provider.filter_choices(
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

        The kind is the collection's, so Plex libraries that disagree give no
        advice.
        """
        rule = body.rule
        types = await self._access.library_types(e.library_id for e in rule.libraries)
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(session, None, rule)
        # The kind matters on Plex alone: elsewhere a collection is regular.
        advice = [
            recommend_kind(
                library.criteria,
                self.capabilities(types[library.library_id], [library.library_id]),
                media_type=types[library.library_id],
                order=policy.order_type,
            )
            for library in rule.libraries
            if self._access.plex(library.library_id)
        ]
        if not advice:
            return None
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
        """What each library's criteria select."""
        rule = body.rule
        scopes = await self._access.scopes(
            rule.libraries, body.collection_id, smart=rule.smart
        )
        async with self._access.database.read_session() as session:
            group = (
                (await self._access.require(session, body.collection_id)).group
                if body.collection_id is not None
                else None
            )
            policy = await self._access.policy(session, group, rule)
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
        self._validator.criteria(library_id, media_type, criteria, smart=rule.smart)
        server = self._access.server_type(library_id)
        smart = rule.smart and server is ServerType.PLEX
        local = all(
            field_available(condition.field, server, media_type, smart=False)
            for condition in criteria.field_conditions()
        )
        # Plex answers for a smart collection, so the preview is what it shows;
        # lists and fields Plex lacks only become labels Plex can test once the
        # collection is saved.
        plex_native = not criteria.source_conditions() and not any(
            labelled_field(condition.field, server, media_type)
            for condition in criteria.field_conditions()
        )
        if smart and plex_native:
            total, ids = await self._access.library_provider(library_id).find_matching(
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
        if smart and not local:
            raise PublicServiceError(
                422,
                "Save the collection to preview Plex filters with lists or "
                "fields Plex lacks",
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
