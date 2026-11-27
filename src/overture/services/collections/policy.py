"""Collection policy resolution, from explicit choices to global defaults."""

lazy from dataclasses import dataclass, fields
lazy from datetime import date
lazy from typing import Any

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.settings import AppSettings
lazy from ...domain import (
    DEFAULT_COLLECTION_ORDER,
    POLICY_SETTINGS,
    ArtStyle,
    AutoArtSource,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    CollectionPosterStyle,
    SyncMode,
)
lazy from ...schemas.collections import CollectionGroupPolicy, CollectionRuleWrite
lazy from ...utils.collection_formats import is_within_active_window

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
    #: The sources Automatic art tries, first to last.
    auto_art: tuple[AutoArtSource, ...]
    generated_style: ArtStyle
    #: Generated posters show the collection's title alone, without its group.
    generated_title_only: bool
    #: The OvertureDB poster styles taken, first to last.
    overturedb_posters: tuple[CollectionPosterStyle, ...]
    backgrounds: bool
    themes: bool
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
    request_missing: bool = False
    member_label: str | None = None
    arr_tag: str | None = None
    home_order: int | None = None

    @property
    def contributed_style(self) -> CollectionPosterStyle:
        """What a poster chosen for the collection is contributed to OvertureDB as.

        The first style it takes; Individual when it takes no OvertureDB poster.
        """
        return next(iter(self.overturedb_posters), CollectionPosterStyle.INDIVIDUAL)


def active_window(
    row: MediaCollection, policy: CollectionPolicy
) -> tuple[str | None, str | None]:
    """The MM-DD dates a collection runs from and to: its own, else its policy's."""
    return (
        row.active_start_mmdd or policy.active_start_mmdd,
        row.active_end_mmdd or policy.active_end_mmdd,
    )


def out_of_season(row: MediaCollection, policy: CollectionPolicy, today: date) -> bool:
    """Whether *today* falls outside the dates the collection runs."""
    return not is_within_active_window(*active_window(row, policy), today)


def resolve_policy(
    defaults: AppSettings,
    group: CollectionGroup | CollectionGroupPolicy | None = None,
    rule: RuleOrPolicy = None,
) -> CollectionPolicy:
    """Resolve nullable rule, group and application defaults in that order.

    A setting with a global default (:data:`POLICY_SETTINGS`) always resolves
    to a value; the others stay unset unless a group or collection sets them.
    """

    def tiers(name: str) -> list[Any]:
        return [
            getattr(tier, name) if tier is not None else None for tier in (rule, group)
        ]

    values: dict[str, Any] = {
        name: inherit(*tiers(name), getattr(defaults, POLICY_SETTINGS[name]))
        if name in POLICY_SETTINGS
        else inherit_optional(*tiers(name))
        for name in _POLICY_FIELDS
    }
    # JSON columns load their values as plain strings.
    values["auto_art"] = tuple(AutoArtSource(source) for source in values["auto_art"])
    values["overturedb_posters"] = tuple(
        CollectionPosterStyle(style) for style in values["overturedb_posters"]
    )
    # Plex orders a smart collection by its query, never by hand, so an
    # inherited Custom passes to the next tier.
    values["order_type"] = inherit(
        rule.order_type if rule else None,
        *(
            order
            for order in (
                group.order_type if group else None,
                defaults.collection_order_default,
                DEFAULT_COLLECTION_ORDER,
            )
            if not (rule is not None and rule.smart and order is CollectionOrder.CUSTOM)
        ),
    )
    return CollectionPolicy(**values)


_POLICY_FIELDS = tuple(field.name for field in fields(CollectionPolicy))
