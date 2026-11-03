"""Contract generator behavior."""

lazy from typing import Any

lazy from overture.db.models.settings import AppSettingsBase
lazy from scripts.generate_settings_defaults import render_settings_defaults
lazy from scripts.generate_ws_types import (
    TypeScriptRenderer,
    api_tags,
    openapi_schema_names,
)


def test_renderer_quotes_non_identifier_property_names() -> None:
    renderer = TypeScriptRenderer()

    rendered = renderer.schema_to_ts(
        {
            "type": "object",
            "properties": {
                "normal_name": {"type": "string"},
                "X-Plex-Token": {"type": "string"},
                "123invalid": {"type": "number"},
            },
            "required": ["normal_name"],
        }
    )

    assert "normal_name: string;" in rendered
    assert '"X-Plex-Token"?: string;' in rendered
    assert '"123invalid"?: number;' in rendered


def test_renderer_parenthesizes_array_item_unions() -> None:
    renderer = TypeScriptRenderer()

    rendered = renderer.schema_to_ts(
        {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ]
            },
        }
    )

    assert rendered == "(string | null)[]"


def test_renderer_indents_nested_object_property_types() -> None:
    renderer = TypeScriptRenderer()

    rendered = renderer.schema_to_ts(
        {
            "type": "object",
            "properties": {
                "target": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
        }
    )

    assert ("  target?: {\n    [key: string]: string;\n  };") in rendered


def test_renderer_resolves_named_component_references_before_render_order() -> None:
    renderer = TypeScriptRenderer()
    renderer.add_named_definitions(
        {
            "Child": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            }
        }
    )

    renderer.render_named_schema(
        "Parent",
        {
            "type": "object",
            "properties": {"child": {"$ref": "#/components/schemas/Child"}},
            "required": ["child"],
        },
    )

    rendered = renderer.text()
    assert "export interface Child" in rendered
    assert "child: Child;" in rendered


# Models that also appear in openapi.json are imported from the generated REST
# bundle instead of being redeclared, so both generators describe one type
# universe and cannot drift into structurally identical twins.


def _shared_renderer(*names: str) -> TypeScriptRenderer:
    return TypeScriptRenderer(shared_types=frozenset(names))


def test_a_shared_model_is_imported_instead_of_redeclared() -> None:
    renderer = _shared_renderer("MediaItemRead")

    renderer.render_named_schema(
        "MediaItemRead",
        {"type": "object", "properties": {"id": {"type": "integer"}}},
    )

    rendered = renderer.text()
    assert 'import type { MediaItemRead } from "./rest/types.gen";' in rendered
    assert "export interface MediaItemRead" not in rendered


def test_a_shared_model_is_re_exported_from_the_ws_module() -> None:
    renderer = _shared_renderer("MediaItemRead")

    renderer.render_named_schema("MediaItemRead", {"type": "object", "properties": {}})

    assert 'export type { MediaItemRead } from "./rest/types.gen";' in renderer.text()


def test_a_ws_only_model_is_declared_locally() -> None:
    """Event payloads absent from openapi.json have nowhere else to come from."""
    renderer = _shared_renderer("MediaItemRead")

    renderer.render_named_schema(
        "BulkArtJobEvent",
        {"type": "object", "properties": {"done": {"type": "integer"}}},
    )

    rendered = renderer.text()
    assert "export interface BulkArtJobEvent" in rendered
    assert "import type" not in rendered


def test_a_shared_model_pulls_in_the_shared_models_it_references() -> None:
    """A nested model is never rendered once its parent is imported, so it has
    to be imported too or importers of that name break."""
    renderer = _shared_renderer("RealtimeSnapshot", "RealtimeJobSnapshot")

    renderer.render_named_schema(
        "RealtimeSnapshot",
        {
            "type": "object",
            "properties": {"jobs": {"$ref": "#/$defs/RealtimeJobSnapshot"}},
            "$defs": {
                "RealtimeJobSnapshot": {
                    "type": "object",
                    "properties": {"kind": {"type": "string"}},
                }
            },
        },
    )

    rendered = renderer.text()
    import_line = next(
        line for line in rendered.splitlines() if line.startswith("import type")
    )
    assert "RealtimeSnapshot" in import_line
    assert "RealtimeJobSnapshot" in import_line
    assert "export interface RealtimeJobSnapshot" not in rendered
    assert "export interface RealtimeSnapshot" not in rendered


def test_a_local_model_may_reference_an_imported_one() -> None:
    renderer = _shared_renderer("PublicError")

    renderer.render_named_schema(
        "JobMetadata",
        {
            "type": "object",
            "properties": {"error": {"$ref": "#/$defs/PublicError"}},
            "$defs": {
                "PublicError": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                }
            },
        },
    )

    rendered = renderer.text()
    assert 'import type { PublicError } from "./rest/types.gen";' in rendered
    assert "export interface JobMetadata" in rendered
    assert "error?: PublicError;" in rendered


def test_no_import_block_is_emitted_when_nothing_is_shared() -> None:
    renderer = TypeScriptRenderer()

    renderer.render_named_schema("Local", {"type": "object", "properties": {}})

    assert "import type" not in renderer.text()


def test_openapi_schema_names_reads_the_component_schemas() -> None:
    document: dict[str, Any] = {
        "components": {"schemas": {"MediaItemRead": {}, "PublicError": {}}}
    }

    assert openapi_schema_names(document) == frozenset({"MediaItemRead", "PublicError"})
    assert openapi_schema_names({}) == frozenset()


def test_api_tags_name_every_tag_an_operation_carries() -> None:
    document = {
        "paths": {
            "/a": {"get": {"tags": ["library"]}, "post": {"tags": ["backups"]}},
            "/b": {"get": {"tags": ["library"]}},
        }
    }

    assert 'export type ApiTag = "backups" | "library";' in api_tags(document)


def test_render_settings_defaults_emits_all_declared_fields() -> None:
    """Settings defaults contract includes every field declared on AppSettingsBase."""
    rendered = render_settings_defaults()
    assert "export const DEFAULT_APP_SETTINGS = {" in rendered
    assert "export type AppSettingsDefaults = typeof DEFAULT_APP_SETTINGS;" in rendered

    for name in AppSettingsBase.model_fields:
        assert f"  {name}: " in rendered
