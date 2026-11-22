"""The checks every collection write passes before anything is saved."""

lazy from collections.abc import Collection, Iterable, Mapping

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
lazy from ...utils.collection_fields import (
    DIMENSIONS,
    available_orders,
    dimension_available,
    field_available,
    field_label,
    field_operators,
    labelled_field,
    library_field_available,
    smart_only_dimension,
)
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.text import spoken_list
lazy from .access import CollectionAccess
lazy from .policy import CollectionPolicy
lazy from .sources import SourceResolver

_PLEX_ONLY_SMART = "Smart collections need a library on a Plex server"


class CollectionValidator:
    """Refuse what the media servers or the configured sources cannot do.

    A collection may span servers that differ in what they keep: a choice is
    accepted when one of its servers can keep it, and the others fall back to
    their nearest (:mod:`overture.utils.collection_fields`). Criteria belong
    to one library, so they are checked against its server.
    """

    def __init__(self, *, access: CollectionAccess, sources: SourceResolver) -> None:
        self._access = access
        self._sources = sources

    def display(
        self,
        options: CollectionOptions | CollectionPolicyBase | CollectionMembersUpdate,
        media_types: Collection[MediaType],
        *,
        smart: bool,
        servers: Collection[ServerType],
    ) -> None:
        """Require each display choice to be one some of *servers* can keep."""
        plex = ServerType.PLEX in servers
        if (
            not isinstance(options, CollectionMembersUpdate)
            and not plex
            and (
                options.collection_mode not in {None, CollectionMode.DEFAULT}
                or options.visible_home
                or options.visible_shared
                or options.visible_library
                or options.collection_filtering is not None
            )
        ):
            raise PublicServiceError(422, "Visibility and home promotion require Plex")
        if smart and options.order_type is CollectionOrder.CUSTOM and plex:
            raise PublicServiceError(422, SMART_CUSTOM_ORDER)
        if options.order_type is not None and not any(
            all(
                options.order_type
                in available_orders(
                    server, media_type, smart=smart and server is ServerType.PLEX
                )
                for media_type in media_types
            )
            for server in servers
        ):
            raise PublicServiceError(
                422, "None of the media servers can order collections this way"
            )

    def criteria(
        self,
        library_id: str,
        media_type: MediaType,
        criteria: FilterGroup,
        *,
        smart: bool,
    ) -> None:
        """Require one library's criteria to be ones its server, or Overture, tests.

        A smart collection is smart only on Plex; on another server Overture
        evaluates the same criteria.
        """
        server = self._access.server_type(library_id)
        smart = smart and server is ServerType.PLEX
        for condition in criteria.field_conditions():
            if not field_available(condition.field, server, media_type, smart=smart):
                label = field_label(condition.field, server)
                raise PublicServiceError(
                    422,
                    f"{label} is only available in Plex smart collections"
                    if field_available(condition.field, server, media_type, smart=True)
                    else f"{label} is not available for "
                    f"{self._library_scope(library_id, media_type)}",
                )
            if condition.operator not in field_operators(condition.field, smart=smart):
                raise PublicServiceError(
                    422,
                    f"{field_label(condition.field, server)} cannot be tested with "
                    f"{condition.operator.label}"
                    + (" in Plex smart collections" if smart else ""),
                )
        self._sources_available(media_type, criteria)

    def library_criteria(
        self,
        media_type: MediaType,
        criteria: FilterGroup,
        servers: Collection[ServerType],
    ) -> None:
        """Require a library filter to test only what some of *servers*' titles can.

        Raises:
            PublicServiceError: 422 for a field or operator the libraries'
                titles cannot be tested with, or a source that is unavailable.
        """
        for condition in criteria.field_conditions():
            available = [
                server
                for server in servers
                if library_field_available(condition.field, server, media_type)
            ]
            label = field_label(condition.field, next(iter(available or servers)))
            if not available:
                raise PublicServiceError(
                    422,
                    f"{label} is not available for {media_type.plural} on "
                    f"{spoken_list(server.display_name for server in sorted(servers))}",
                )
            if condition.operator not in field_operators(condition.field, smart=False):
                raise PublicServiceError(
                    422,
                    f"{label} cannot be tested with {condition.operator.label}",
                )
        self._sources_available(media_type, criteria)

    def _sources_available(self, media_type: MediaType, criteria: FilterGroup) -> None:
        for condition in criteria.source_conditions():
            self._sources.require(condition.source.type, media_type)
            if isinstance(condition.source, TmdbChartSource) and not chart_available(
                media_type, condition.source.chart
            ):
                raise PublicServiceError(
                    422,
                    f"TMDB has no {condition.source.chart.value.replace('_', ' ')} "
                    f"chart of {media_type.plural}",
                )

    def _library_scope(self, library_id: str, media_type: MediaType) -> str:
        """Name a library's titles as a message does: "movies on Plex"."""
        title = self._access.library_provider(library_id).server.title
        return f"{media_type.plural} on {title}"

    def smart_set(self, library_ids: Iterable[str], *, smart: bool) -> None:
        """Require a smart set to span a Plex library, which alone keeps it smart."""
        if smart and ServerType.PLEX not in self._access.server_types(library_ids):
            raise PublicServiceError(422, _PLEX_ONLY_SMART)

    def rule(
        self,
        types: Mapping[str, MediaType],
        rule: CollectionRuleWrite,
        policy: CollectionPolicy,
    ) -> None:
        """Check each library's criteria against what that library holds."""
        servers = self._access.server_types(types)
        if rule.smart and ServerType.PLEX not in servers:
            raise PublicServiceError(422, _PLEX_ONLY_SMART)
        for library in rule.libraries:
            self.criteria(
                library.library_id,
                types[library.library_id],
                library.criteria,
                smart=rule.smart,
            )
        self.display(
            rule.model_copy(update={"order_type": policy.order_type}),
            set(types.values()),
            smart=rule.smart,
            servers=servers,
        )

    def generator(
        self, library_id: str, media_type: MediaType, generator: CollectionGeneratorBase
    ) -> None:
        """Require a set's dimension and criteria to suit one of its libraries.

        A smart set is smart on Plex libraries; see :meth:`smart_set`.
        """
        server = self._access.server_type(library_id)
        smart = generator.smart and server is ServerType.PLEX
        dimension = DIMENSIONS[generator.dimension]
        if not dimension_available(
            generator.dimension, server, media_type, smart=smart
        ):
            raise PublicServiceError(
                422,
                f"{dimension.label} need a set of Plex smart collections"
                if dimension_available(
                    generator.dimension, server, media_type, smart=True
                )
                else f"{dimension.label} are not available for "
                f"{self._library_scope(library_id, media_type)}",
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
                self.criteria(library_id, media_type, criteria, smart=False)
            if smart:
                self.criteria(library_id, media_type, criteria, smart=True)
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
