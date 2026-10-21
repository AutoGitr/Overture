"""Keep workflow permissions, pins, checks and label references consistent."""

lazy import json
lazy import re
lazy import tomllib
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy import yaml

lazy from scripts.sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[2]


def _required_uv_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        version = tomllib.load(project_file)["tool"]["uv"]["required-version"]
    assert isinstance(version, str)
    return version


def _assert_job_steps(steps: list[dict[str, Any]], required_uv: str) -> None:
    for step in steps:
        uses = step.get("uses", "")
        if uses:
            assert re.fullmatch(r"[\w-]+/[\w-]+(?:/[\w.-]+)*@[0-9a-f]{40}", uses)
        if uses.startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False
        if uses.startswith("astral-sh/setup-uv@"):
            # uv reads Python's version from .python-version.
            assert step["with"] == {"version": required_uv}
        run = step.get("run", "")
        assert "${{" not in run
        assert not re.search(r"uv run (?!\-\-locked)", run)


def test_workflows_pin_actions_bound_runtime_and_do_not_persist_credentials() -> None:
    required_uv = _required_uv_version()
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        raw = path.read_text()
        workflow = yaml.safe_load(raw)
        assert "permissions" in workflow, path.name
        for action in re.findall(r"(?m)^\s*-?\s*uses: (.+)$", raw):
            assert re.fullmatch(
                r"\./\.github/workflows/[\w-]+\.yml", action
            ) or re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", action), (
                f"{path.name}: {action}"
            )
        for job in workflow["jobs"].values():
            if "uses" in job:
                assert re.fullmatch(r"\./\.github/workflows/[\w-]+\.yml", job["uses"])
                continue
            assert re.fullmatch(r"ubuntu-\d{2}\.04", job["runs-on"])
            assert job["timeout-minutes"] <= 40
            _assert_job_steps(job["steps"], required_uv)


def test_codeql_scans_python_typescript_and_actions() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    matrix = workflow["jobs"]["analyze"]["strategy"]["matrix"]["include"]
    languages = {entry["language"] for entry in matrix}
    assert languages == {"python", "javascript-typescript", "actions"}


def test_release_workflow_triggers_on_semver_tags_and_dispatch() -> None:
    raw = (ROOT / ".github/workflows/release.yml").read_text()
    workflow = yaml.safe_load(raw)
    # PyYAML reads the bare `on` key as True.
    triggers = workflow[True]
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+"]
    assert "release.yml@${{ github.ref }}" in raw
    assert "--generate-notes" in raw


def test_labels_in_templates_release_notes_and_renovate_exist_in_manifest() -> None:
    labels = load_labels()
    names = {label["name"] for label in labels}
    assert len(names) == len(labels)

    for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
        form = yaml.safe_load(path.read_text())
        assert set(form.get("labels", [])) <= names

    release_notes = yaml.safe_load((ROOT / ".github/release.yml").read_text())[
        "changelog"
    ]
    assert set(release_notes["exclude"]["labels"]) <= names
    for category in release_notes["categories"]:
        category_labels = set(category.get("labels", [])) - {"*"}
        assert category_labels <= names

    renovate = json.loads((ROOT / ".github/renovate.json").read_text())
    assert set(renovate["labels"]) <= names
    assert set(renovate["vulnerabilityAlerts"]["labels"]) <= names
    for rule in renovate["packageRules"]:
        assert set(rule.get("addLabels", [])) <= names

    sibling_manifest = ROOT.parent / "OvertureDB/.github/labels.json"
    if sibling_manifest.is_file():
        sibling_by_name = {
            item["name"]: item for item in json.loads(sibling_manifest.read_text())
        }
        for label in labels:
            assert sibling_by_name.get(label["name"]) == label


def test_runner_updates_are_enabled_without_automatic_os_upgrades() -> None:
    renovate = json.loads((ROOT / ".github/renovate.json").read_text())
    rule = next(
        rule
        for rule in renovate["packageRules"]
        if "github-runners" in rule.get("matchDatasources", [])
    )
    assert rule["enabled"] is True
    assert rule["automerge"] is False
    # Runner releases have no timestamps, so an age requirement blocks updates.
    assert rule["minimumReleaseAge"] is None


@pytest.mark.parametrize(
    ("path", "required"),
    [
        ("src/overture/main.py", {"backend", "contracts", "container"}),
        ("pyproject.toml", {"backend", "contracts", "container"}),
        ("uv.lock", {"backend", "contracts", "container"}),
        ("frontend/package.json", {"frontend", "contracts", "container"}),
        ("frontend/bun.lock", {"frontend", "contracts", "container"}),
        (".agents/skills.json", {"contracts"}),
        ("openapi/overture.json", {"contracts"}),
        ("packaging/linux/build.py", {"backend", "container"}),
        (".github/workflows/native.yml", {"backend"}),
        (".github/workflows/codeql.yml", {"backend"}),
    ],
)
def test_ci_filters_cover_build_and_contract_inputs(
    path: str, required: set[str]
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    script = workflow["jobs"]["changes"]["steps"][1]["run"]
    filters = re.findall(
        r"if has_changed '([^']+)'; then\s+echo \"(\w+)=true\"", script
    )
    selected = {job for pattern, job in filters if re.search(pattern, path)}
    assert required <= selected


def test_async_database_dependency_is_declared_and_locked() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert any(
        dependency.startswith("sqlalchemy[asyncio]==")
        for dependency in project["project"]["dependencies"]
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert any(package["name"] == "greenlet" for package in lock["package"])
