"""Collection policy resolution, from explicit choices to global defaults."""

lazy from dataclasses import dataclass

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.settings import AppSettings
lazy from ...domain import (
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    SyncMode,
)
lazy from ...schemas.collections import CollectionGroupPolicy, CollectionRuleWrite

type RuleOrPolicy = CollectionRule | CollectionRuleWrite | None


def inherit[T](*values: T | None) -> T:
    """Preserve false and empty-string overrides while walking the tiers."""
    for value in values:
        if value is not None:
            return value
    raise ValueError("A policy must have a global default")


def inherit_optional[T](*values: T | None) -> T | None:
    """Return the first non-null value across the tiers, or ``None``."""
    for value in values:
        if value is not None:
            return value
    return None


@dataclass(slots=True, frozen=True)
class CollectionPolicy:
    """Effective values for one collection workflow."""

    sync_mode: SyncMode
    minimum_items: int
    delete_below_minimum: bool
    auto_match_art: bool
    auto_match_theme: bool
    collection_mode: CollectionMode
    order_type: CollectionOrder
    collection_filtering: CollectionFiltering
    visible_home: bool
    visible_shared: bool
    visible_library: bool
    sort_title_format: str
    summary_format: str
    active_start_mmdd: str | None = None
    active_end_mmdd: str | None = None
    delete_when_inactive: bool = False
    sync_interval_hours: int = 24
    sync_enabled: bool = True


def resolve_policy(
    defaults: AppSettings,
    group: CollectionGroup | CollectionGroupPolicy | None = None,
    rule: RuleOrPolicy = None,
) -> CollectionPolicy:
    """Resolve nullable rule, group and application defaults in that order."""
    return CollectionPolicy(
        sync_mode=inherit(
            rule.sync_mode if rule else None,
            group.sync_mode if group else None,
            defaults.collection_sync_mode,
        ),
        minimum_items=inherit(
            rule.minimum_items if rule else None,
            group.minimum_items if group else None,
            defaults.collection_minimum_items,
        ),
        delete_below_minimum=inherit(
            rule.delete_below_minimum if rule else None,
            group.delete_below_minimum if group else None,
            defaults.collection_delete_below_minimum,
        ),
        auto_match_art=inherit(
            rule.auto_match_art if rule else None,
            group.auto_match_art if group else None,
            defaults.collection_auto_match_art,
        ),
        auto_match_theme=inherit(
            rule.auto_match_theme if rule else None,
            group.auto_match_theme if group else None,
            defaults.collection_auto_match_theme,
        ),
        collection_mode=inherit(
            rule.collection_mode if rule else None,
            group.collection_mode if group else None,
            defaults.collection_mode_default,
        ),
        order_type=inherit(
            rule.order_type if rule else None,
            group.order_type if group else None,
            defaults.collection_order_default,
        ),
        collection_filtering=inherit(
            rule.collection_filtering if rule else None,
            group.collection_filtering if group else None,
            defaults.collection_filtering_default,
        ),
        visible_home=inherit(
            rule.visible_home if rule else None,
            group.visible_home if group else None,
            defaults.collection_visible_home,
        ),
        visible_shared=inherit(
            rule.visible_shared if rule else None,
            group.visible_shared if group else None,
            defaults.collection_visible_shared,
        ),
        visible_library=inherit(
            rule.visible_library if rule else None,
            group.visible_library if group else None,
            defaults.collection_visible_library,
        ),
        sort_title_format=inherit(
            rule.sort_title_format if rule else None,
            group.sort_title_format if group else None,
            defaults.collection_sort_title_format,
        ),
        summary_format=inherit(
            rule.summary_format if rule else None,
            group.summary_format if group else None,
            defaults.collection_summary_format,
        ),
        active_start_mmdd=inherit_optional(
            rule.active_start_mmdd if rule else None,
            group.active_start_mmdd if group else None,
        ),
        active_end_mmdd=inherit_optional(
            rule.active_end_mmdd if rule else None,
            group.active_end_mmdd if group else None,
        ),
        delete_when_inactive=inherit(
            rule.delete_when_inactive if rule else None,
            group.delete_when_inactive if group else None,
            defaults.collection_delete_when_inactive,
        ),
        sync_interval_hours=inherit(
            rule.sync_interval_hours if rule else None,
            group.sync_interval_hours if group else None,
            defaults.collection_sync_interval_hours,
        ),
        sync_enabled=inherit(
            rule.enabled if rule else None,
            group.sync_enabled if group else None,
            defaults.collection_sync_enabled,
        ),
    )
