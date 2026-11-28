"""What Overture and OvertureDB share stays the same on both sides.

Every file or setting the two repositories share is listed here, so one table
says what must match. The catalog contract is checked byte for byte by
``scripts.catalog_contract --check`` instead, which also copies it; the preset
schema and vocabulary in it are generated from Overture's models.

OvertureDB is read from ``OVERTUREDB_DIR`` or beside this checkout. Without
it these tests skip, unless ``OVERTURE_REQUIRE_SIBLING`` is set, as CI sets it
where OvertureDB is checked out.
"""

lazy import json
lazy import os
lazy import tomllib
lazy from pathlib import Path

lazy import pytest

lazy from overture.schemas.collection_presets import CollectionPresetFile
lazy from scripts.preset_contract import generated

ROOT = Path(__file__).resolve().parents[2]
#: The Renovate preset both repositories extend.
SHARED_RENOVATE = ".github/renovate-shared"
#: Lint rules only Overture needs: FastAPI's.
OVERTURE_ONLY_RULES = frozenset({"FAST"})


@pytest.fixture
def overturedb() -> Path:
    """The OvertureDB checkout."""
    path = Path(os.environ.get("OVERTUREDB_DIR", ROOT.parent / "OvertureDB"))
    if not (path / "schema").is_dir():
        message = f"OvertureDB is not checked out at {path}"
        if os.environ.get("OVERTURE_REQUIRE_SIBLING"):
            pytest.fail(message)
        pytest.skip(message)
    return path


def test_every_overture_label_is_overturedbs_too(overturedb: Path) -> None:
    """OvertureDB adds labels of its own, such as contribution kinds."""
    path = ".github/labels.json"
    theirs = {
        label["name"]: label for label in json.loads((overturedb / path).read_text())
    }
    for label in json.loads((ROOT / path).read_text()):
        assert theirs.get(label["name"]) == label


def test_overturedb_takes_every_renovate_rule_from_the_shared_preset(
    overturedb: Path,
) -> None:
    renovate = json.loads((overturedb / ".github/renovate.json").read_text())
    assert renovate["extends"] == [f"github>AutoGitr/Overture//{SHARED_RENOVATE}"]
    assert set(renovate) <= {"$schema", "description", "extends"}


def test_shared_tool_settings_match(overturedb: Path) -> None:
    ours = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]
    theirs = tomllib.loads((overturedb / "pyproject.toml").read_text())["tool"]
    for key in ("target-version", "line-length", "indent-width", "format"):
        assert theirs["ruff"][key] == ours["ruff"][key], key
    assert set(theirs["ruff"]["lint"]["select"]) == (
        set(ours["ruff"]["lint"]["select"]) - OVERTURE_ONLY_RULES
    )
    for key in (
        "typeCheckingMode",
        "pythonVersion",
        "pythonPlatform",
        "reportUnnecessaryTypeIgnoreComment",
        "reportImplicitOverride",
        "reportPropertyTypeMismatch",
        "reportUninitializedInstanceVariable",
    ):
        assert theirs["pyright"][key] == ours["pyright"][key], key
    for key in ("minversion", "strict", "filterwarnings", "verbosity_subtests"):
        assert theirs["pytest"][key] == ours["pytest"][key], key


def test_overturedbs_preset_contract_is_generated_from_overtures_models(
    overturedb: Path,
) -> None:
    for name, text in generated().items():
        assert (overturedb / "schema" / name).read_text() == text, name


def test_every_overturedb_preset_is_one_overture_can_add(overturedb: Path) -> None:
    presets = sorted((overturedb / "data/presets").glob("*.json"))
    assert presets
    for path in presets:
        preset = CollectionPresetFile.model_validate_json(path.read_text())
        assert preset.preset is not None
        assert preset.preset.id == path.stem
