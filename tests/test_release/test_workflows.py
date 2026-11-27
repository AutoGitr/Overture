"""Keep workflow permissions, pins, checks and label references consistent."""

lazy import json
lazy import re
lazy import tomllib
lazy from pathlib import Path, PurePosixPath
lazy from typing import Any

lazy import pytest
lazy import yaml

lazy from scripts.sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[2]
#: The Renovate preset both repositories extend.
SHARED_RENOVATE = ".github/renovate-shared"


def renovate_config() -> dict[str, Any]:
    """Overture's Renovate config merged over the shared preset it extends."""
    own = json.loads((ROOT / ".github/renovate.json").read_text())
    shared = json.loads((ROOT / f"{SHARED_RENOVATE}.json").read_text())
    assert own["extends"] == [f"local>AutoGitr/Overture//{SHARED_RENOVATE}"]
    return {**shared, "packageRules": shared["packageRules"] + own["packageRules"]}


def test_the_container_builds_with_the_pinned_uv_python_and_bun() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    uv = project["tool"]["uv"]["required-version"]
    python = (ROOT / ".python-version").read_text().strip()
    assert project["project"]["requires-python"] == f"=={python}"
    package = json.loads((ROOT / "frontend/package.json").read_text())
    bun = package["packageManager"].removeprefix("bun@")
    assert package["engines"]["bun"] == bun
    docs = json.loads((ROOT / "docs/package.json").read_text())
    assert docs["packageManager"] == package["packageManager"]
    assert docs["engines"]["bun"] == bun
    assert re.findall(r"(?m)^FROM astral/uv:([^@\s]+)@", dockerfile) == [uv]
    assert re.findall(r"(?m)^FROM python:([^-@\s]+)-slim@", dockerfile) == [python]
    assert re.findall(r"oven/bun:([^-@\s]+)-slim@", dockerfile) == [bun]


def _assert_job_steps(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        uses = step.get("uses", "")
        if uses:
            assert re.fullmatch(r"[\w-]+/[\w-]+(?:/[\w.-]+)*@[0-9a-f]{40}", uses)
        if uses.startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False
        if uses.startswith("astral-sh/setup-uv@"):
            # setup-uv installs the required-version from pyproject.toml, and
            # uv reads Python's version from .python-version; a job that
            # publishes builds from no cache another run could have written.
            assert step.get("with", {}) in ({}, {"enable-cache": False})
        if uses.startswith("oven-sh/setup-bun@"):
            assert step["with"] == {"bun-version-file": "frontend/package.json"}
        run = step.get("run", "")
        assert "${{" not in run
        assert not re.search(r"uv run (?!\-\-locked)", run)


def test_workflows_pin_actions_bound_runtime_and_do_not_persist_credentials() -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        raw = path.read_text()
        workflow = yaml.safe_load(raw)
        # Each job names the permissions it needs, in one place, so none takes
        # more than its own; the repository's default token reads only.
        assert "permissions" not in workflow, path.name
        assert all("permissions" in job for job in workflow["jobs"].values()), path.name
        for action in re.findall(r"(?m)^\s*-?\s*uses: (.+)$", raw):
            assert re.fullmatch(
                r"\./\.github/workflows/[\w-]+\.yml", action
            ) or re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", action), (
                f"{path.name}: {action}"
            )
        for job in workflow["jobs"].values():
            assert "${{ matrix." not in job.get("name", ""), path.name
            if "uses" in job:
                assert re.fullmatch(r"\./\.github/workflows/[\w-]+\.yml", job["uses"])
                continue
            assert re.fullmatch(r"ubuntu-\d{2}\.04", job["runs-on"])
            assert job["timeout-minutes"] <= 40
            _assert_job_steps(job["steps"])


def _filtered_in(path: str, patterns: list[str]) -> bool:
    """Whether a change to *path* starts a run, as GitHub reads ``paths``.

    The last pattern a path matches decides, and a ``!`` pattern excludes it.
    """
    included = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        if PurePosixPath(path).full_match(pattern.removeprefix("!")):
            included = not negated
    return included


@pytest.mark.parametrize(
    ("path", "analysed"),
    [
        ("src/overture/main.py", True),
        ("scripts/release_metadata.py", True),
        ("packaging/linux/build.py", True),
        ("frontend/src/App.svelte", True),
        ("frontend/vite.config.ts", True),
        (".github/workflows/ci.yml", True),
        (".github/codeql/codeql-config.yml", True),
        ("tests/test_api.py", False),
        ("frontend/src/test/e2e/fixtures.ts", False),
        ("frontend/src/generated/rest/types.gen.ts", False),
        ("frontend/package.json", False),
        ("uv.lock", False),
        (".github/README.md", False),
        ("docs/overture/index.md", False),
        ("Dockerfile", False),
    ],
)
def test_codeql_runs_for_analysed_code_and_then_analyses_every_language(
    path: str, *, analysed: bool
) -> None:
    """Every run analyses every language, so code scanning compares it with main's."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    # PyYAML reads the ``on`` key as ``True``.
    triggers = workflow[True]
    patterns = triggers["pull_request"]["paths"]
    assert triggers["push"]["paths"] == patterns
    assert _filtered_in(path, patterns) is analysed
    job = workflow["jobs"]["analyze"]
    # The analysis itself is shared with OvertureDB.
    assert job["uses"] == "./.github/workflows/codeql-analysis.yml"
    assert set(json.loads(job["with"]["languages"])) == {
        "python",
        "javascript-typescript",
        "actions",
    }


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

    renovate = renovate_config()
    assert set(renovate["labels"]) <= names
    assert set(renovate["vulnerabilityAlerts"]["labels"]) <= names
    for rule in renovate["packageRules"]:
        assert set(rule.get("addLabels", [])) <= names


def test_runner_updates_are_enabled_without_automatic_os_upgrades() -> None:
    renovate = renovate_config()
    rule = next(
        rule
        for rule in renovate["packageRules"]
        if "github-runners" in rule.get("matchDatasources", [])
    )
    assert rule["enabled"] is True
    assert rule["automerge"] is False
    # Runner releases have no timestamps, so an age requirement blocks updates.
    assert rule["minimumReleaseAge"] is None
    unpinned_tools = next(
        rule for rule in renovate["packageRules"] if rule.get("pinDigests") is False
    )
    assert set(unpinned_tools["matchPackageNames"]) == {
        "aquasecurity/trivy",
        "sigstore/cosign",
    }


def test_shared_tools_keep_their_group_over_broader_ones() -> None:
    """Renovate applies later rules over earlier ones: a shared group comes last."""
    groups = [
        rule["groupName"]
        for rule in renovate_config()["packageRules"]
        if "groupName" in rule
    ]
    for shared in (
        "Tooling, Linters & Testing Rules",
        "Python Version",
        "uv",
        "Catalog contract",
    ):
        for broad in ("Docker Infrastructure", "Backend Core", "Frontend Core", "Docs"):
            assert groups.index(shared) > groups.index(broad)


APP = {"backend", "contracts", "container", "e2e"}
WEB = {"frontend", "container", "e2e"}
DEPENDENCIES = APP


@pytest.mark.parametrize(
    ("path", "selected"),
    [
        ("src/overture/main.py", APP | {"duplication"}),
        ("pyproject.toml", DEPENDENCIES),
        ("uv.lock", DEPENDENCIES),
        ("frontend/src/App.svelte", WEB | {"duplication"}),
        ("frontend/package.json", WEB | {"contracts", "backend", "duplication"}),
        ("frontend/bun.lock", WEB | {"contracts", "duplication"}),
        (
            "frontend/src/generated/rest/types.gen.ts",
            WEB | {"contracts", "duplication"},
        ),
        ("scripts/contracts.py", {"backend", "contracts", "duplication"}),
        (".github/labels.json", {"backend"}),
        (".github/renovate-shared.json", {"backend"}),
        ("tests/test_release/test_shared_files.py", {"backend"}),
        ("scripts/release_metadata.py", {"backend", "duplication"}),
        ("frontend/index.html", WEB | {"backend"}),
        ("tests/test_api.py", {"backend"}),
        ("tests/test_release/test_capacity.py", {"backend"}),
        (".agents/skills.json", {"contracts"}),
        (".jscpd.json", {"duplication"}),
        ("openapi/overture.json", {"contracts"}),
        ("Dockerfile", {"dockerfile", "backend", "container"}),
        ("compose.yaml", {"backend", "container"}),
        ("packaging/linux/build.py", {"backend", "native"}),
        ("packaging/linux/test.Dockerfile", {"native"}),
        (".github/workflows/native.yml", {"backend", "native"}),
        (".github/workflows/codeql.yml", {"backend"}),
        (".github/CHANGELOG.md", {"backend"}),
        ("AGENTS.md", {"backend"}),
        ("docs/overture/index.md", {"duplication"}),
        ("docs/package.json", {"backend"}),
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


def test_the_contributor_guide_lives_only_in_the_docs() -> None:
    """GitHub's file points at the docs page, so the guide is written once."""
    pointer = (ROOT / ".github/CONTRIBUTING.md").read_text()
    assert "/overture/developer/contributing" in pointer
    assert pointer.count("\n") < 10
    assert (ROOT / "docs/overture/developer/contributing.md").is_file()
