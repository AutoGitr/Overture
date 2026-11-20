"""Resolving a collection's settings from its own, its group's and the global ones."""

lazy from dataclasses import fields

lazy from overture.db.models.collection_group import CollectionGroup
lazy from overture.db.models.settings import AppSettings
lazy from overture.domain import POLICY_SETTINGS, SEPARATED_SORT_TITLE, ArtStyle
lazy from overture.schemas.collections import CollectionPolicyBase, CollectionRuleWrite
lazy from overture.services.collections.policy import CollectionPolicy, resolve_policy


def test_every_global_default_names_a_policy_setting_and_an_application_one() -> None:
    policy = {field.name for field in fields(CollectionPolicy)}
    assert POLICY_SETTINGS.keys() <= policy
    assert POLICY_SETTINGS.keys() <= CollectionPolicyBase.model_fields.keys()
    assert set(POLICY_SETTINGS.values()) <= AppSettings.model_fields.keys()


def test_a_collection_overrides_its_group_which_overrides_the_default() -> None:
    defaults = AppSettings(collection_generated_style=ArtStyle.DARK)
    group = CollectionGroup(name="Sagas", generated_style=ArtStyle.LIGHT, home_order=2)

    assert resolve_policy(defaults).generated_style is ArtStyle.DARK
    assert resolve_policy(defaults, group).generated_style is ArtStyle.LIGHT
    assert resolve_policy(defaults, group).home_order == 2
    assert resolve_policy(defaults).home_order is None
    rule = CollectionRuleWrite.model_construct(
        generated_style=ArtStyle.ACCENT, smart=False, order_type=None
    )
    assert resolve_policy(defaults, group, rule).generated_style is ArtStyle.ACCENT


def test_a_separator_sorts_its_group_unless_a_sort_title_is_set() -> None:
    separated = CollectionGroup(name="Sagas", separator=True)

    assert resolve_policy(AppSettings(), separated).sort_title_format == (
        SEPARATED_SORT_TITLE
    )
    assert (
        resolve_policy(AppSettings(collection_sort_title_format="{title}"), separated)
    ).sort_title_format == "{title}"
    separated.sort_title_format = ""
    assert resolve_policy(AppSettings(), separated).sort_title_format == ""
