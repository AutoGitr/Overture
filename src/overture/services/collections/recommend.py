"""Whether a rule suits a Plex smart collection or a regular one."""

lazy from ...domain import CollectionKind, CollectionOrder, MediaType, ServerType
lazy from ...schemas.collections import (
    CollectionCapabilities,
    CollectionRuleWrite,
    FieldCondition,
    KindRecommendation,
)
lazy from .fields import FIELDS, field_available, field_operators


def _tests(
    condition: FieldCondition, server: ServerType, media_type: MediaType, *, smart: bool
) -> bool:
    """Whether Overture, or Plex if *smart*, can evaluate the condition itself."""
    return field_available(
        condition.field, server, media_type, smart=smart
    ) and condition.operator in field_operators(condition.field, smart=smart)


def _named(condition: FieldCondition) -> str:
    return (
        f"{FIELDS[condition.field].label} {condition.operator.value.replace('_', ' ')}"
    )


def recommend_kind(
    rule: CollectionRuleWrite,
    capabilities: CollectionCapabilities,
    *,
    media_type: MediaType,
    order: CollectionOrder,
) -> KindRecommendation | None:
    """Return the kind that serves *rule* best and why; ``None`` without a choice.

    A filter only Plex knows needs a smart collection and a custom order a
    regular one. Otherwise a rule Plex can evaluate whole, as a native filter in
    an order it sorts by, suits a smart collection, which Plex keeps current
    per user without a sync; one that needs lists, tags, TMDB facts or an
    operator Plex lacks suits a regular one, which Overture fills on each sync.
    """
    if not capabilities.smart:
        return None
    server = capabilities.server_type
    conditions = rule.criteria.field_conditions()
    sources = rule.criteria.source_conditions()
    plex_cannot = next(
        (c for c in conditions if not _tests(c, server, media_type, smart=True)), None
    )
    overture_cannot = next(
        (c for c in conditions if not _tests(c, server, media_type, smart=False)),
        None,
    )
    if overture_cannot is not None:
        # Neither kind can test both, so the rule must change, not the kind.
        if plex_cannot is not None:
            return None
        return KindRecommendation(
            kind=CollectionKind.SMART,
            reason=f"Only Plex can test {_named(overture_cannot)}.",
        )
    if order not in capabilities.smart_orders:
        return KindRecommendation(
            kind=CollectionKind.REGULAR,
            reason="Plex cannot keep a custom order."
            if order is CollectionOrder.CUSTOM
            else "Plex cannot sort a smart collection in this order.",
        )
    if plex_cannot is not None:
        return KindRecommendation(
            kind=CollectionKind.REGULAR,
            reason=f"Plex has no filter for {_named(plex_cannot)}, so Overture "
            "evaluates it on each sync.",
        )
    if sources:
        return KindRecommendation(
            kind=CollectionKind.REGULAR,
            reason="Lists and tags have no Plex filter, so Overture syncs their "
            "members.",
        )
    return KindRecommendation(
        kind=CollectionKind.SMART,
        reason="Plex filters every condition natively, so it keeps the members "
        "current, with play state per user, without waiting for a sync.",
    )
