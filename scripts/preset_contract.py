"""Write or check the preset schema and vocabulary in an OvertureDB checkout.

Overture's models define what a preset may hold, so OvertureDB validates its
presets against files generated from them; ``catalog_contract`` then copies
them back like the rest of the contract.
"""

lazy import argparse
lazy import json
lazy from collections.abc import Callable
lazy from pathlib import Path
lazy from typing import Any

lazy from overture.domain import (
    FilterField,
    MediaType,
    ServerType,
    SetDimension,
    SourceType,
    TmdbChart,
)
lazy from overture.integrations.tmdb import chart_available
lazy from overture.schemas.collection_presets import CollectionPresetFile
lazy from overture.services.collections.sources import (
    selects_media,
    source_integration,
)
lazy from overture.utils.collection_fields import (
    DIMENSIONS,
    FIELDS,
    OPERATORS,
    dimension_available,
    field_available,
)

_SMART = (False, True)


def _media_types(test: Callable[[MediaType], bool]) -> list[str]:
    return [media_type.value for media_type in MediaType if test(media_type)]


def _field_media(field: FilterField) -> list[str]:
    """Where some server tests the field, in a regular or a smart collection."""
    return _media_types(
        lambda media_type: any(
            field_available(field, server, media_type, smart=smart)
            for server in ServerType
            for smart in _SMART
        )
    )


def _dimension_media(dimension: SetDimension) -> list[str]:
    """Where some server can run a set of the dimension."""
    return _media_types(
        lambda media_type: any(
            dimension_available(dimension, server, media_type, smart=smart)
            for server in ServerType
            for smart in _SMART
        )
    )


def _source_media(source: SourceType) -> list[str]:
    return _media_types(lambda media_type: selects_media(source, media_type))


def _chart_media(chart: TmdbChart) -> list[str]:
    return _media_types(lambda media_type: chart_available(media_type, chart))


def _source_requires(source: SourceType) -> str | None:
    integration = source_integration(source)
    return integration.value if integration else None


def _dimension_requires(dimension: SetDimension) -> str | None:
    field = DIMENSIONS[dimension].field
    if field is not None:
        return "tmdb" if FIELDS[field].tmdb else None
    if dimension is SetDimension.FRANCHISE:
        return _source_requires(SourceType.TMDB_COLLECTION)
    return None


def vocabulary() -> dict[str, Any]:
    """What preset criteria, sources and sets may name, and where each works."""
    return {
        "fields": {
            field.value: {
                "kind": spec.kind.value,
                "media_types": _field_media(field),
                "portable": spec.portable,
                "requires": "tmdb" if spec.tmdb else None,
            }
            for field, spec in FIELDS.items()
        },
        "operators": {
            kind.value: [operator.value for operator in operators]
            for kind, operators in OPERATORS.items()
        },
        "sources": {
            source.value: {
                "media_types": _source_media(source),
                "requires": _source_requires(source),
            }
            for source in SourceType
        },
        "charts": {chart.value: _chart_media(chart) for chart in TmdbChart},
        "dimensions": {
            dimension.value: {
                "media_types": _dimension_media(dimension),
                "requires": _dimension_requires(dimension),
            }
            for dimension in SetDimension
        },
    }


def generated() -> dict[str, str]:
    """Each generated contract file's name and text."""
    schema = CollectionPresetFile.model_json_schema(mode="validation")
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    return {
        name: json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        for name, value in (
            ("preset.schema.json", schema),
            ("preset-vocabulary.json", vocabulary()),
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="OvertureDB checkout")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, text in generated().items():
        target = args.source / "schema" / name
        if args.check:
            if not target.exists() or target.read_text() != text:
                print(
                    f"OvertureDB's {name} differs from Overture's models. "
                    "Update it with: uv run python -m scripts.preset_contract "
                    "<OvertureDB checkout> (run in Overture), then copy the "
                    "contract back with scripts.catalog_contract"
                )
                return 1
        else:
            target.write_text(text, newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
