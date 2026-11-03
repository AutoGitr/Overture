"""The checks every collection write passes before anything is saved."""

lazy from ...domain import (
    SMART_CUSTOM_ORDER,
    CollectionMode,
    CollectionOrder,
    FilterOperator,
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
    FIELDS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
    smart_only_dimension,
)
lazy from .policy import CollectionPolicy
lazy from .sources import SourceResolver


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
            raise PublicServiceError(
                422, "Smart collections are only supported by Plex"
            )
        for condition in criteria.field_conditions():
            if not field_available(condition.field, server, media_type, smart=smart):
                label = field_label(condition.field, server)
                raise PublicServiceError(
                    422,
                    f"{label} is only available in Plex smart collections"
                    if field_available(condition.field, server, media_type, smart=True)
                    else f"{label} is not available for this library",
                )
            plex = FIELDS[condition.field].plex
            if (
                smart
                and condition.operator is FilterOperator.IS_NOT
                and plex is not None
                and not plex.negatable
            ):
                raise PublicServiceError(
                    422,
                    f"Plex smart collections cannot test that "
                    f"{field_label(condition.field, server)} is not a value",
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
        for criteria in (
            generator.criteria,
            *(value.criteria for value in generator.custom_values),
        ):
            if not smart_only_dimension(generator.dimension, server, media_type):
                self.criteria(media_type, criteria, smart=False)
            if generator.smart:
                self.criteria(media_type, criteria, smart=True)
        if (
            generator.smart
            and dimension.field is not None
            and not field_available(dimension.field, server, media_type, smart=True)
        ):
            raise PublicServiceError(
                422, f"Plex smart collections cannot test {dimension.label}"
            )
