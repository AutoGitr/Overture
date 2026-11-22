"""Release metadata stays consistent with the canonical project version."""

lazy import json
lazy from datetime import date
lazy from pathlib import Path

lazy import pytest

lazy from overture.version import APP_VERSION
lazy from scripts.release_metadata import (
    CHANGELOG,
    REQUIRED_RELEASE_FILES,
    format_changelog,
    prepare_release,
    project_version,
    release_notes,
    require_api_entry,
    validate_release,
)

TODAY = date(2026, 10, 21)
UNRELEASED_CHANGELOG = """# Changelog

## Unreleased

### 🐛 Bug fixes

- **Themes:** saved themes play again.

## 1.0.0 - 2026-09-01

### 🚀 Features

- First release.
"""


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
    (root / CHANGELOG).write_text(UNRELEASED_CHANGELOG)


def test_application_and_release_metadata_use_project_version() -> None:
    assert project_version() == APP_VERSION
    assert validate_release() == APP_VERSION


def test_tag_must_match_the_project_version() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_release(tag="v9.9.9")


def test_release_requires_the_operator_documents(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.2.3")
    (tmp_path / REQUIRED_RELEASE_FILES[-1]).unlink()

    with pytest.raises(ValueError, match="missing release files"):
        validate_release(tmp_path)


def test_prepare_release_updates_versions_and_releases_the_changelog(
    tmp_path: Path,
) -> None:
    _seed_release_tree(tmp_path, "1.0.0")

    assert prepare_release("v1.2.3", tmp_path, today=TODAY) == "1.2.3"

    assert validate_release(tmp_path, tag="v1.2.3") == "1.2.3"
    changelog = (tmp_path / CHANGELOG).read_text()
    assert changelog.startswith(
        "# Changelog\n\n## Unreleased\n\n## 1.2.3 - 2026-10-21\n\n### 🐛 Bug fixes\n"
    )
    notes = release_notes("1.2.3", tmp_path)
    assert notes == "### 🐛 Bug fixes\n\n- **Themes:** saved themes play again.\n"


def test_prepare_release_requires_unreleased_entries(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.0.0")
    (tmp_path / CHANGELOG).write_text("## Unreleased\n\n### 🐛 Bug fixes\n")

    with pytest.raises(ValueError, match="no unreleased entries"):
        prepare_release("1.0.1", tmp_path, today=TODAY)


def test_prepare_release_refuses_a_released_version(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.0.0")

    with pytest.raises(ValueError, match=r"already has a 1\.0\.0 section"):
        prepare_release("1.0.0", tmp_path, today=TODAY)


def test_tagged_release_requires_its_changelog_section(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.2.3")

    assert validate_release(tmp_path) == "1.2.3"
    with pytest.raises(ValueError, match=r"no entries for 1\.2\.3"):
        validate_release(tmp_path, tag="v1.2.3")


@pytest.mark.parametrize(
    ("changelog", "error"),
    [
        ("## 1.0.0 - 2026-09-01\n\n- First.\n", "must start with"),
        ("## Unreleased\n\n## 1.0.0\n\n- First.\n", "no release date"),
        ("## Unreleased\n\n### Improved\n\n- Faster.\n", "unknown change types"),
        ("## Unreleased\n\n### Fixed\n\n- **Art:** a.\n", "unknown change types"),
        ("## Unreleased\n\n### 🐛 Bug fixes\n\n- Faster.\n", "one line each"),
        ("## Unreleased\n\n- **Art:** faster.\n", "under a change type"),
        (
            (
                "## Unreleased\n\n### 🐛 Bug fixes\n\n"
                "- **Art:** faster.\n- **Art:** faster.\n"
            ),
            "repeats an entry",
        ),
        (
            (
                "## Unreleased\n\n### 🐛 Bug fixes\n\n- **Art:** b.\n\n"
                "### 🚀 Features\n\n- **Art:** a.\n"
            ),
            "out of order",
        ),
        (
            "## Unreleased\n\n## 1.0.0 - 2026-09-01\n\n## 1.0.0 - 2026-09-01\n",
            r"more than one 1\.0\.0 section",
        ),
    ],
)
def test_validate_release_rejects_malformed_changelogs(
    tmp_path: Path, changelog: str, error: str
) -> None:
    _seed_release_tree(tmp_path, "1.0.0")
    (tmp_path / CHANGELOG).write_text(changelog)

    with pytest.raises(ValueError, match=error):
        validate_release(tmp_path)


@pytest.mark.parametrize("bad_version", ["1.2", "1.2.3-rc1", "abc"])
def test_prepare_release_rejects_non_stable_semver(
    tmp_path: Path, bad_version: str
) -> None:
    _seed_release_tree(tmp_path, "1.0.0")

    with pytest.raises(ValueError, match="stable semantic version"):
        prepare_release(bad_version, tmp_path, today=TODAY)


def test_validate_release_rejects_drifted_version_files(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path, "1.2.3")
    (tmp_path / "frontend" / "package.json").write_text(
        '{\n  "name": "overture",\n  "version": "1.0.0"\n}\n'
    )

    with pytest.raises(ValueError, match=r"frontend/package\.json version '1\.0\.0'"):
        validate_release(tmp_path)


def test_unreleased_entries_are_ordered_by_change_type_then_area(
    tmp_path: Path,
) -> None:
    _seed_release_tree(tmp_path, "1.0.0")
    released = (
        "## 1.0.0 - 2026-09-01\n\n### 🐛 Bug fixes\n\n- **Zoo:** z.\n- **Art:** a.\n"
    )
    (tmp_path / CHANGELOG).write_text(
        "# Changelog\n\n## Unreleased\n\n### 🐛 Bug fixes\n\n- **Themes:** t.\n\n"
        "### 🚀 Features\n\n"
        "- **Themes:** first.\n- **Art:** a.\n- **Themes:** second.\n\n" + released
    )

    format_changelog(tmp_path)

    # Within an area, the order written stays; released sections stay as written.
    assert (tmp_path / CHANGELOG).read_text() == (
        "# Changelog\n\n## Unreleased\n\n### 🚀 Features\n\n- **Art:** a.\n"
        "- **Themes:** first.\n- **Themes:** second.\n\n### 🐛 Bug fixes\n\n"
        "- **Themes:** t.\n\n" + released
    )
    assert validate_release(tmp_path) == "1.0.0"


def test_an_incompatible_api_change_needs_an_api_changelog_line(tmp_path: Path) -> None:
    _seed_release_tree(tmp_path)
    changelog = tmp_path / CHANGELOG
    changelog.write_text(
        "# Changelog\n\n## Unreleased\n\n### 🐛 Bug fixes\n\n- **Sync:** A fix.\n"
    )
    with pytest.raises(ValueError, match=r"add a - \*\*API:\*\* line"):
        require_api_entry(tmp_path)

    # Named, but not as breaking.
    changelog.write_text(
        "# Changelog\n\n## Unreleased\n\n### 🌟 Enhancements\n\n"
        "- **API:** `ignores_case` names how criteria match a field.\n"
    )
    with pytest.raises(ValueError, match="Breaking Changes"):
        require_api_entry(tmp_path)

    changelog.write_text(
        "# Changelog\n\n## Unreleased\n\n### 🚨 Breaking Changes\n\n"
        "- **API:** IDs are at most 9007199254740991.\n"
    )
    require_api_entry(tmp_path)
