"""Release metadata stays consistent with the canonical project version."""

lazy import json
lazy from pathlib import Path

lazy import pytest

lazy from overture.version import APP_VERSION
lazy from scripts.release_metadata import (
    REQUIRED_RELEASE_FILES,
    project_version,
    set_release_version,
    validate_release,
)


def _seed_release_tree(root: Path, version: str = "1.0.0") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "overture"\nversion = "{version}"\n'
    )
    (root / "uv.lock").write_text(
        f'[[package]]\nname = "overture"\nversion = "{version}"\n'
    )
    (root / "frontend").mkdir(parents=True, exist_ok=True)
    (root / "frontend" / "package.json").write_text(
        json.dumps({"name": "overture", "version": version}, indent=2) + "\n"
    )
    (root / "openapi").mkdir(parents=True, exist_ok=True)
    (root / "openapi" / "overture.json").write_text(
        json.dumps(
            {"info": {"title": "Overture", "version": version}, "openapi": "3.1.0"},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    for name in REQUIRED_RELEASE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("present\n")


def test_application_and_release_metadata_use_project_version() -> None:
    assert project_version() == APP_VERSION
    assert validate_release() == APP_VERSION


def test_tag_must_match_the_project_version() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_release(tag="v9.9.9")


def test_release_requires_the_operator_documents(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.2.3")
    (tmp_path / REQUIRED_RELEASE_FILES[0]).unlink()

    with pytest.raises(ValueError, match="missing release files"):
        validate_release(tmp_path)


def test_set_release_version_updates_all_versioned_files(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.0.0")

    assert set_release_version("v1.2.3", tmp_path) == "1.2.3"
    assert validate_release(tmp_path, tag="v1.2.3") == "1.2.3"


@pytest.mark.parametrize("bad_version", ["1.2", "1.2.3-rc1", "abc"])
def test_set_release_version_rejects_non_stable_semver(
    tmp_path: Path, bad_version: str
) -> None:
    _seed_release_tree(tmp_path, "1.0.0")

    with pytest.raises(ValueError, match="stable semantic version"):
        set_release_version(bad_version, tmp_path)


def test_validate_release_rejects_drifted_version_files(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.2.3")
    (tmp_path / "frontend" / "package.json").write_text(
        '{\n  "name": "overture",\n  "version": "1.0.0"\n}\n'
    )

    with pytest.raises(ValueError, match=r"frontend/package\.json version '1\.0\.0'"):
        validate_release(tmp_path)
