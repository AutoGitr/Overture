"""A collection's display options: inherited from policy and sent to the server."""

lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import CollectionFiltering, CollectionKind, CollectionOrder
lazy from ...media_servers.adapters import CollectionDetails
lazy from ...media_servers.errors import MediaServerError
lazy from ...schemas.collections import CollectionOptions
lazy from ...utils.collection_fields import kept_order
lazy from ...utils.collection_formats import format_sort_title, format_summary
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .policy import CollectionPolicy, RuleOrPolicy
lazy from .sync_outcome import CopyChange

#: Display options a rule records when a collection sets them explicitly.
DISPLAY_OVERRIDES = frozenset(
    {
        "collection_mode",
        "order_type",
        "collection_filtering",
        "visible_home",
        "visible_shared",
        "visible_library",
    }
)


def saved_options(
    row: MediaCollection, rule: CollectionRule | None
) -> CollectionOptions:
    """The options a stored collection was saved with."""
    options = CollectionOptions(
        title=row.title,
        collection_group=row.group_name,
        tmdb_collection_id=row.tmdb_collection_id,
        sort_title_format=row.sort_title_format,
        summary_format=row.summary_format,
        active_start_mmdd=row.active_start_mmdd,
        active_end_mmdd=row.active_end_mmdd,
        delete_when_inactive=row.delete_when_inactive,
    )
    if rule is None:
        # Imported server display choices remain explicit.
        options = options.model_copy(
            update={
                **row.model_dump(include=set(DISPLAY_OVERRIDES)),
                "summary": row.summary if row.summary_format is None else None,
                "sort_title": row.sort_title if row.sort_title_format is None else None,
            }
        )
    return options


def inherited_sort_title(
    options: CollectionOptions, policy: CollectionPolicy
) -> str | None:
    template = (
        options.sort_title_format
        if options.sort_title_format is not None
        else policy.sort_title_format
    )
    if options.sort_title_format is None and options.sort_title is not None:
        return options.sort_title
    if not template:
        return options.sort_title
    try:
        return format_sort_title(
            template,
            title=options.title,
            group=options.collection_group,
        )
    except ValueError as exc:
        raise PublicServiceError(422, str(exc)) from exc


def inherited_summary(
    options: CollectionOptions,
    policy: CollectionPolicy,
    source_summary: str | None,
) -> str | None:
    template = (
        options.summary_format
        if options.summary_format is not None
        else policy.summary_format
    )
    if not template:
        # Without a template, a collection's own summary wins over its list's.
        return options.summary or source_summary
    if (
        options.summary_format is None
        and options.summary is not None
        and "{summary}" not in template
    ):
        return options.summary
    try:
        return format_summary(
            template,
            title=options.title,
            group=options.collection_group,
            start_date=options.active_start_mmdd or policy.active_start_mmdd,
            end_date=options.active_end_mmdd or policy.active_end_mmdd,
            summary=options.summary,
            source_summary=source_summary,
        )
    except ValueError as exc:
        raise PublicServiceError(422, str(exc)) from exc


def _explicit[T](options: CollectionOptions, name: str, inherited: T) -> T:
    """An option the caller set, even to nothing, else the inherited value."""
    return getattr(options, name) if name in options.model_fields_set else inherited


def resolved_order(
    options: CollectionOptions, policy: CollectionPolicy
) -> CollectionOrder:
    """The order the collection keeps: its own, or without one the policy's."""
    return options.order_type or policy.order_type


class CollectionDisplay:
    """Resolve a collection's effective display options and send them to the server."""

    def __init__(self, *, access: CollectionAccess) -> None:
        self._access = access

    async def effective(
        self,
        row: MediaCollection,
        options: CollectionOptions,
        rule: RuleOrPolicy = None,
    ) -> CollectionOptions:
        """Return the options the server shows, with the group's defaults filled in."""
        return (await self._resolve(row, options, rule))[0]

    async def _resolve(
        self, row: MediaCollection, options: CollectionOptions, rule: RuleOrPolicy
    ) -> tuple[CollectionOptions, CollectionPolicy]:
        if rule is None:
            rule = row.rule
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(
                session,
                await self._access.group(session, options.collection_group),
                rule,
            )
        sort_title = inherited_sort_title(options, policy)
        template = (
            options.summary_format
            if options.summary_format is not None
            else policy.summary_format
        )
        summary_options = options
        if options.summary is None and (not template or "{summary}" in template):
            summary_options = options.model_copy(update={"summary": row.summary_source})
        summary = inherited_summary(
            summary_options,
            policy,
            rule.source_summary if isinstance(rule, CollectionRule) else None,
        )
        order = resolved_order(options, policy)
        visible_home = _explicit(options, "visible_home", policy.visible_home)
        visible_shared = _explicit(options, "visible_shared", policy.visible_shared)
        visible_library = _explicit(options, "visible_library", policy.visible_library)
        filtering = options.collection_filtering or (
            policy.collection_filtering
            if row.kind is CollectionKind.SMART
            or policy.collection_filtering is not CollectionFiltering.ADMIN
            else None
        )
        mode = options.collection_mode or policy.collection_mode
        effective = options.model_copy(
            update={
                "sort_title": sort_title,
                "summary": summary,
                "order_type": order,
                "visible_home": visible_home,
                "visible_shared": visible_shared,
                "visible_library": visible_library,
                "collection_mode": mode,
                "collection_filtering": filtering,
            }
        )
        return effective, policy

    async def push(
        self, row: MediaCollection, options: CollectionOptions, rule: RuleOrPolicy
    ) -> tuple[CollectionOptions, list[CopyChange]]:
        """Send the effective options to every server copy.

        Each server keeps what it can: the order falls back to the default
        where it cannot keep it, and only Plex copies are smart. Returns the
        options, and the copies whose server refused them, which leaves the
        others to take theirs.
        """
        effective, policy = await self._resolve(row, options, rule)
        refused: list[CopyChange] = []
        for copy in self._access.copies(row):
            if copy.server_item_id is None:
                continue
            provider = self._access.provider(copy.server_id)
            smart = row.kind is CollectionKind.SMART and self._access.plex(
                copy.lead.library_id
            )
            try:
                await provider.update_collection_details(
                    copy.server_item_id,
                    copy.lead.library_id,
                    CollectionDetails(
                        title=effective.title,
                        summary=effective.summary,
                        sort_title=effective.sort_title,
                        mode=options.collection_mode or policy.collection_mode,
                        order=kept_order(
                            resolved_order(effective, policy),
                            provider.server_type,
                            copy.lead.media_type,
                            smart=smart,
                        ),
                        smart=smart,
                        visible_home=effective.visible_home,
                        visible_shared=effective.visible_shared,
                        visible_library=effective.visible_library,
                        filtering=effective.collection_filtering,
                        hub=row.kind is not CollectionKind.SEPARATOR,
                    ),
                )
            except MediaServerError as exc:
                refused.append(CopyChange.failed(copy, exc))
        return effective, refused
