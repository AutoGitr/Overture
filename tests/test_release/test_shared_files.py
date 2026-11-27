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
lazy import re
lazy import tomllib
lazy from pathlib import Path
lazy from typing import Any

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


def _project(root: Path) -> dict[str, Any]:
    return tomllib.loads((root / "pyproject.toml").read_text())


def _pins(project: dict[str, Any]) -> dict[str, str]:
    """Each exactly pinned dependency of a project, in any group, by name."""
    groups = project.get("dependency-groups", {}).values()
    requirements = [
        *project["project"].get("dependencies", []),
        *(entry for group in groups for entry in group if isinstance(entry, str)),
    ]
    return {
        name.split("[")[0].strip().lower(): version.split(";")[0].strip()
        for name, _, version in (
            requirement.partition("==") for requirement in requirements
        )
        if version
    }


def test_the_python_version_files_are_identical(overturedb: Path) -> None:
    path = ".python-version"
    assert (overturedb / path).read_text() == (ROOT / path).read_text()


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


def test_shared_tools_and_python_match(overturedb: Path) -> None:
    ours, theirs = _project(ROOT), _project(overturedb)
    assert theirs["project"]["requires-python"] == ours["project"]["requires-python"]
    assert (
        theirs["tool"]["uv"]["required-version"]
        == (ours["tool"]["uv"]["required-version"])
    )
    for key in ("target-version", "line-length", "indent-width", "format"):
        assert theirs["tool"]["ruff"][key] == ours["tool"]["ruff"][key], key
    assert set(theirs["tool"]["ruff"]["lint"]["select"]) == (
        set(ours["tool"]["ruff"]["lint"]["select"]) - OVERTURE_ONLY_RULES
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
        assert theirs["tool"]["pyright"][key] == ours["tool"]["pyright"][key], key
    for key in ("minversion", "strict", "filterwarnings", "verbosity_subtests"):
        assert theirs["tool"]["pytest"][key] == ours["tool"]["pytest"][key], key


def test_a_dependency_both_pin_has_one_version(overturedb: Path) -> None:
    ours, theirs = _pins(_project(ROOT)), _pins(_project(overturedb))
    shared = ours.keys() & theirs.keys()
    assert shared, "the repositories share no pinned dependency"
    assert {name: theirs[name] for name in shared} == {
        name: ours[name] for name in shared
    }


def _workflow_actions(root: Path) -> dict[str, set[str]]:
    """Each external GitHub Action a repository's workflows use, with its pins."""
    actions: dict[str, set[str]] = {}
    for path in (root / ".github/workflows").glob("*.yml"):
        for repo, digest in re.findall(
            r"(?m)^\s*-?\s*uses:\s*([\w-]+/[\w-]+)(?:/[\w.-]+)*@([0-9a-f]{40})\b",
            path.read_text(),
        ):
            actions.setdefault(repo, set()).add(digest)
    return actions


def test_a_github_action_both_use_has_one_commit_digest(overturedb: Path) -> None:
    ours, theirs = _workflow_actions(ROOT), _workflow_actions(overturedb)
    shared = ours.keys() & theirs.keys()
    assert shared, "the repositories share no GitHub Action"
    assert {name: theirs[name] for name in shared} == {
        name: ours[name] for name in shared
    }


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
