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
    """Return the kind that suits *rule* and why, where the server has smart ones."""
    if not capabilities.smart:
        return None
    if rule.criteria.source_conditions():
        return CollectionKind.REGULAR, "Lists and tags need Overture to sync members"
    for condition in rule.criteria.field_conditions():
        if not field_available(
            condition.field, capabilities.server_type, media_type, smart=True
        ):
            label = FIELDS[condition.field].label
            return CollectionKind.REGULAR, f"Plex cannot test {label}"
    if order is CollectionOrder.CUSTOM:
        return CollectionKind.REGULAR, "Plex cannot keep a custom order"
    return CollectionKind.SMART, "Plex keeps it current without syncs"
