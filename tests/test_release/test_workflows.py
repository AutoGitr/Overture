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


def test_the_container_builds_with_the_required_uv() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        required = tomllib.load(project_file)["tool"]["uv"]["required-version"]
    images = re.findall(
        r"(?m)^FROM astral/uv:([^@\s]+)@", (ROOT / "Dockerfile").read_text()
    )
    assert images == [required]


def _assert_job_steps(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        uses = step.get("uses", "")
        if uses:
            assert re.fullmatch(r"[\w-]+/[\w-]+(?:/[\w.-]+)*@[0-9a-f]{40}", uses)
        if uses.startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False
        if uses.startswith("astral-sh/setup-uv@"):
            # setup-uv installs the required-version from pyproject.toml, and
            # uv reads Python's version from .python-version.
            assert "with" not in step
        run = step.get("run", "")
        assert "${{" not in run
        assert not re.search(r"uv run (?!\-\-locked)", run)


def test_workflows_pin_actions_bound_runtime_and_do_not_persist_credentials() -> None:
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
            _assert_job_steps(job["steps"])


_CODEQL_EXCLUDED = re.compile(r"grep -Ev '([^']+)' <<< \"\$changed\"")
_CODEQL_LANGUAGE = re.compile(
    r"grep -Eq '([^']+)' <<< \"\$code\"; then\s+languages\+=\('\"([\w-]+)\"'\)"
)
NO_LANGUAGE: frozenset[str] = frozenset()


@pytest.mark.parametrize(
    ("path", "languages"),
    [
        ("src/overture/main.py", frozenset({"python"})),
        ("scripts/release_metadata.py", frozenset({"python"})),
        ("frontend/src/App.svelte", frozenset({"javascript-typescript"})),
        ("frontend/vite.config.ts", frozenset({"javascript-typescript"})),
        (".github/workflows/ci.yml", frozenset({"actions"})),
        ("tests/test_api.py", NO_LANGUAGE),
        ("frontend/src/test/e2e/fixtures.ts", NO_LANGUAGE),
        ("frontend/package.json", NO_LANGUAGE),
        ("uv.lock", NO_LANGUAGE),
        (".github/README.md", NO_LANGUAGE),
        ("Dockerfile", NO_LANGUAGE),
    ],
)
def test_codeql_analyses_only_the_languages_a_change_touches(
    path: str, languages: frozenset[str]
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    script = workflow["jobs"]["languages"]["steps"][1]["run"]
    assert """all='["python","javascript-typescript","actions"]'""" in script
    excluded = _CODEQL_EXCLUDED.search(script)
    assert excluded
    selected = {
        language
        for pattern, language in _CODEQL_LANGUAGE.findall(script)
        if re.search(pattern, path) and not re.search(excluded[1], path)
    }
    assert selected == languages


def test_release_workflow_triggers_on_semver_tags_and_dispatch() -> None:
    raw = (ROOT / ".github/workflows/release.yml").read_text()
    workflow = yaml.safe_load(raw)
    # PyYAML reads the bare `on` key as True.
    triggers = workflow[True]
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+"]
    assert "release.yml@${{ github.ref }}" in raw
    assert "--notes-file release-notes.md" in raw


def test_labels_in_templates_and_renovate_exist_in_manifest() -> None:
    labels = load_labels()
    names = {label["name"] for label in labels}
    assert len(names) == len(labels)

    for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
        form = yaml.safe_load(path.read_text())
        assert set(form.get("labels", [])) <= names

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


APP = {"backend", "contracts", "container", "e2e", "release-validation"}
WEB = {"frontend", "container", "e2e", "release-validation"}
DEPENDENCIES = APP | {"native"}


@pytest.mark.parametrize(
    ("path", "selected"),
    [
        ("src/overture/main.py", APP),
        ("pyproject.toml", DEPENDENCIES),
        ("uv.lock", DEPENDENCIES),
        ("frontend/src/App.svelte", WEB),
        ("frontend/package.json", WEB | {"contracts"}),
        ("frontend/bun.lock", WEB | {"contracts"}),
        ("frontend/src/generated/rest/types.gen.ts", WEB | {"contracts"}),
        ("scripts/contracts.py", {"backend", "contracts"}),
        ("scripts/release_metadata.py", {"backend"}),
        ("frontend/index.html", WEB | {"backend"}),
        ("tests/test_api.py", {"backend"}),
        ("tests/test_release/test_capacity.py", {"backend", "release-validation"}),
        (".agents/skills.json", {"contracts"}),
        ("openapi/overture.json", {"contracts"}),
        ("Dockerfile", {"dockerfile", "backend", "container", "native"}),
        ("compose.yaml", {"backend", "container"}),
        ("packaging/linux/build.py", {"backend", "native"}),
        ("packaging/linux/test.Dockerfile", {"native"}),
        (".github/workflows/native.yml", {"backend", "native"}),
        (".github/workflows/codeql.yml", {"backend"}),
        (".github/CHANGELOG.md", {"backend"}),
        ("AGENTS.md", {"backend"}),
    ],
)
def test_ci_runs_exactly_the_jobs_a_change_affects(
    path: str, selected: set[str]
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    script = workflow["jobs"]["changes"]["steps"][1]["run"]
    filters = re.findall(
        r"if has_changed '([^']+)'; then\s+echo \"([\w-]+)=true\"", script
    )
    assert {job for pattern, job in filters if re.search(pattern, path)} == selected


def test_async_database_dependency_is_declared_and_locked() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert any(
        dependency.startswith("sqlalchemy[asyncio]==")
        for dependency in project["project"]["dependencies"]
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert any(package["name"] == "greenlet" for package in lock["package"])
