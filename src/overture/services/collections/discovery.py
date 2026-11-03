"""What criteria the media server can evaluate, and what they select now."""

lazy from collections import Counter

lazy from ...config import Settings
lazy from ...domain import FilterField, MediaType, SetDimension, TmdbChart
lazy from ...integrations.tmdb import chart_available
lazy from ...schemas.collections import (
    CollectionCapabilities,
    CollectionDimensionRead,
    CollectionFieldRead,
    CollectionFieldValue,
    CollectionPreview,
    CollectionPreviewRequest,
    CollectionSourceRead,
    KindRecommendation,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .criteria import field_value
lazy from .fields import (
    DIMENSIONS,
    FIELDS,
    OPERATORS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
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
            fields=sorted(
                (
                    CollectionFieldRead(
                        field=field,
                        label=field_label(field, server),
                        kind=spec.kind,
                        operators=list(OPERATORS[spec.kind]),
                        local=local,
                        smart=smart,
                    )
                    for field, spec in FIELDS.items()
                    if (
                        local := field_available(field, server, media_type, smart=False)
                        and (tmdb or not spec.tmdb)
                    )
                    | (smart := field_available(field, server, media_type, smart=True))
                ),
                key=_by_label,
            ),
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
                await self._access.collection_titles(media_type, library_id)
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
                        title
                        for _, title in await self._access.provider().filter_choices(
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

    async def preview(self, body: CollectionPreviewRequest) -> CollectionPreview:
        """What the criteria select now; Plex counts a smart collection's members."""
        rule = body.rule
        self._validator.criteria(body.media_type, rule.criteria, smart=rule.smart)
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(session, body.media_type, None, rule)
        items = await self._access.library_items(body.library_id, body.media_type)
        recommended = recommend_kind(
            rule,
            self.capabilities(body.media_type),
            media_type=body.media_type,
            order=policy.order_type,
        )
        recommendation = (
            None
            if recommended is None
            else KindRecommendation(kind=recommended[0], reason=recommended[1])
        )
        server = self._access.server_type
        local = all(
            field_available(condition.field, server, body.media_type, smart=False)
            for condition in rule.criteria.field_conditions()
        )
        # Plex answers for a smart collection, so the preview is what it shows;
        # a list only becomes a label Plex can test once the collection is saved.
        if rule.smart and not rule.criteria.source_conditions():
            total, ids = await self._access.provider().find_matching(
                body.library_id,
                body.media_type,
                await self._membership.plex_filter(
                    body.library_id, body.media_type, rule.criteria, policy.order_type
                ),
                _PREVIEW_MEMBERS,
            )
            by_server_id = {item.server_item_id: item.title for item in items}
            return CollectionPreview(
                member_count=min(total, rule.limit or total),
                members=[by_server_id[i] for i in ids if i in by_server_id],
                recommendation=recommendation,
            )
        if rule.smart and not local:
            raise PublicServiceError(
                422, "Save the collection to preview Plex filters with lists"
            )
        wanted = await self._membership.wanted(
            body.media_type,
            body.library_id,
            rule.criteria,
            items,
            order=policy.order_type,
            limit=rule.limit,
        )
        tests_tmdb = any(
            FIELDS[condition.field].tmdb
            for condition in rule.criteria.field_conditions()
        )
        return CollectionPreview(
            member_count=len(wanted),
            members=[item.title for item in wanted[:_PREVIEW_MEMBERS]],
            recommendation=recommendation,
            tmdb_unread=sum(
                item.tmdb_id is not None and item.tmdb_checked_id != item.tmdb_id
                for item in items
            )
            if tests_tmdb
            else 0,
        )
