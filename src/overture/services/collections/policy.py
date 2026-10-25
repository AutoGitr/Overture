"""Collection policy resolution, from explicit choices to global defaults."""

lazy from dataclasses import dataclass

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.settings import AppSettings
lazy from ...domain import CollectionMode, SyncMode
lazy from ...schemas.collections import CollectionGroupPolicy, CollectionRuleWrite


def inherit[T](*values: T | None) -> T:
    """Preserve false and empty-string overrides while walking the tiers."""
    for value in values:
        if value is not None:
            return value
    raise ValueError("A policy must have a global default")


@dataclass(slots=True, frozen=True)
class CollectionPolicy:
    """Effective values for one collection workflow."""

    sync_mode: SyncMode
    minimum_items: int
    delete_below_minimum: bool
    auto_match_art: bool
    auto_match_theme: bool
    collection_mode: CollectionMode
    sort_title_format: str


def resolve_policy(
    defaults: AppSettings,
    group: CollectionGroup | CollectionGroupPolicy | None = None,
    rule: CollectionRule | CollectionRuleWrite | CollectionGroupPolicy | None = None,
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
            group.collection_mode if group else None, defaults.collection_mode_default
        ),
        sort_title_format=inherit(
            group.sort_title_format if group else None,
            defaults.collection_sort_title_format,
        ),
    )
