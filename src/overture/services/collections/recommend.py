"""Whether a rule suits a Plex smart collection or a regular one."""

lazy from ...domain import CollectionKind, CollectionOrder, MediaType
lazy from ...schemas.collections import CollectionCapabilities, CollectionRuleWrite
lazy from .fields import FIELDS, field_available


def recommend_kind(
    rule: CollectionRuleWrite,
    capabilities: CollectionCapabilities,
    *,
    media_type: MediaType,
    order: CollectionOrder,
) -> tuple[CollectionKind, str] | None:
    """Return the kind *rule* needs and why, or ``None`` when either serves it.

    Only a condition one kind cannot evaluate, or an order it cannot keep,
    decides: a filter only Plex knows needs a smart collection, and lists,
    tags and TMDB facts need Overture to sync the members.
    """
    if not capabilities.smart:
        return None
    server = capabilities.server_type
    fields = [condition.field for condition in rule.criteria.field_conditions()]
    local_only = next(
        (f for f in fields if not field_available(f, server, media_type, smart=True)),
        None,
    )
    smart_only = next(
        (f for f in fields if not field_available(f, server, media_type, smart=False)),
        None,
    )
    if smart_only is not None:
        # Neither kind can test both, so the rule must change, not the kind.
        if local_only is not None:
            return None
        return CollectionKind.SMART, f"only Plex can test {FIELDS[smart_only].label}"
    if local_only is not None:
        return CollectionKind.REGULAR, f"Plex cannot test {FIELDS[local_only].label}"
    if rule.criteria.source_conditions():
        return (
            CollectionKind.REGULAR,
            "lists and tags have no Plex filter, so Overture syncs their members",
        )
    if order is CollectionOrder.CUSTOM:
        return CollectionKind.REGULAR, "Plex cannot keep a custom order"
    return None
