"""The checks every collection write passes before anything is saved."""

lazy from ...domain import (
    SMART_CUSTOM_ORDER,
    CollectionMode,
    CollectionOrder,
    MediaType,
    ServerType,
    SetDimension,
    SourceType,
)
lazy from ...integrations.tmdb import chart_available
lazy from ...schemas.collections import (
    CollectionGeneratorBase,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionPolicyBase,
    CollectionRuleWrite,
    FilterGroup,
    TmdbChartSource,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .fields import (
    DIMENSIONS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
    field_operators,
    labelled_field,
    smart_only_dimension,
)
lazy from .policy import CollectionPolicy
lazy from .sources import SourceResolver

_PLEX_ONLY_SMART = "Smart collections are only supported by Plex"


class CollectionValidator:
    """Refuse what the media server or the configured sources cannot do."""

    def __init__(self, *, access: CollectionAccess, sources: SourceResolver) -> None:
        self._access = access
        self._sources = sources

    def display(
        self,
        options: CollectionOptions | CollectionPolicyBase | CollectionMembersUpdate,
        media_type: MediaType,
        *,
        smart: bool,
    ) -> None:
        server = self._access.server_type
        if (
            not isinstance(options, CollectionMembersUpdate)
            and server is not ServerType.PLEX
            and (
                options.collection_mode not in {None, CollectionMode.DEFAULT}
                or options.visible_home
                or options.visible_shared
                or options.visible_library
                or options.collection_filtering is not None
            )
        ):
            raise PublicServiceError(422, "Visibility and home promotion require Plex")
        if options.order_type is not None and options.order_type not in (
            available_orders(server, media_type, smart=smart)
        ):
            raise PublicServiceError(
                422,
                SMART_CUSTOM_ORDER
                if smart and options.order_type is CollectionOrder.CUSTOM
                else "The media server cannot order collections this way",
            )

    def criteria(
        self, media_type: MediaType, criteria: FilterGroup, *, smart: bool
    ) -> None:
        server = self._access.server_type
        if smart and server is not ServerType.PLEX:
            raise PublicServiceError(422, _PLEX_ONLY_SMART)
        for condition in criteria.field_conditions():
            if not field_available(condition.field, server, media_type, smart=smart):
                label = field_label(condition.field, server)
                raise PublicServiceError(
                    422,
                    f"{label} is only available in Plex smart collections"
                    if field_available(condition.field, server, media_type, smart=True)
                    else f"{label} is not available for this library",
                )
            if condition.operator not in field_operators(condition.field, smart=smart):
                raise PublicServiceError(
                    422,
                    f"{field_label(condition.field, server)} cannot be tested with "
                    f"{condition.operator.value.replace('_', ' ')}"
                    + (" in Plex smart collections" if smart else ""),
                )
        for condition in criteria.source_conditions():
            self._sources.require(condition.source.type, media_type)
            if isinstance(condition.source, TmdbChartSource) and not chart_available(
                media_type, condition.source.chart
            ):
                raise PublicServiceError(
                    422, "TMDB has no such chart for this library's titles"
                )

    def rule(
        self, media_type: MediaType, rule: CollectionRuleWrite, policy: CollectionPolicy
    ) -> None:
        self.criteria(media_type, rule.criteria, smart=rule.smart)
        self.display(
            rule.model_copy(update={"order_type": policy.order_type}),
            media_type,
            smart=rule.smart,
        )

    def generator(
        self, media_type: MediaType, generator: CollectionGeneratorBase
    ) -> None:
        server = self._access.server_type
        if generator.smart and server is not ServerType.PLEX:
            raise PublicServiceError(422, _PLEX_ONLY_SMART)
        dimension = DIMENSIONS[generator.dimension]
        if not dimension_available(
            generator.dimension, server, media_type, smart=generator.smart
        ):
            raise PublicServiceError(
                422,
                f"{dimension.label} need a set of Plex smart collections"
                if dimension_available(
                    generator.dimension, server, media_type, smart=True
                )
                else f"{dimension.label} are not available for this library",
            )
        if generator.dimension is SetDimension.FRANCHISE:
            self._sources.require(SourceType.TMDB_COLLECTION, media_type)
        # Overture counts values itself, then Plex may evaluate each collection.
        # Plex counts the values only it knows, so it must test the shared
        # criteria itself rather than through Overture's labels.
        plex_counts = smart_only_dimension(generator.dimension, server, media_type)
        for criteria in (
            generator.criteria,
            *(value.criteria for value in generator.custom_values),
        ):
            if not plex_counts:
                self.criteria(media_type, criteria, smart=False)
            if generator.smart:
                self.criteria(media_type, criteria, smart=True)
        if plex_counts and (
            generator.criteria.source_conditions()
            or any(
                labelled_field(condition.field, server, media_type)
                for condition in generator.criteria.field_conditions()
            )
        ):
            raise PublicServiceError(
                422,
                f"Plex counts {dimension.label.casefold()}, so every collection's "
                "conditions must be ones Plex tests itself",
            )
