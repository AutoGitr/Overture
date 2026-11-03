"""Install, update and verify the agent skills and subagents.

``.agents/skills.json`` lists every skill and subagent and where it comes from:

- ``python``: shipped inside an installed Python package, so it follows
  ``uv.lock``.
- ``npm``: shipped inside an installed frontend package, so it follows
  ``frontend/bun.lock``.
- ``github``: a path in a GitHub repository, pinned to a commit and a content
  hash that ``--update`` moves to the default branch's latest commit.
- ``local``: written for Overture and edited in place in ``.agents/skills``.

Skills install into ``.agents/skills`` and are mirrored into ``.claude/skills``;
subagents install into ``.claude/agents``. Both skill directories hold exactly
the listed skills. ``--check`` verifies everything without writing or using
the network.
"""

lazy import argparse
lazy import hashlib
lazy import importlib.util
lazy import io
lazy import json
lazy import shutil
lazy import sys
lazy import tarfile
lazy import tempfile
lazy import urllib.request
lazy from pathlib import Path, PurePosixPath
lazy from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".agents" / "skills.json"
SKILLS = ROOT / ".agents" / "skills"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"
CLAUDE_AGENTS = ROOT / ".claude" / "agents"
NODE_MODULES = ROOT / "frontend" / "node_modules"

type Entry = dict[str, Any]


def _files(path: Path) -> dict[str, bytes]:
    """Map each file under *path* (or *path* itself) to its LF-normalised bytes.

    Files are ordered by their POSIX name, not by ``Path``, whose ordering
    ignores case on Windows and would change the digest there.
    """
    found = (
        {"": path}
        if path.is_file()
        else {
            file.relative_to(path).as_posix(): file
            for file in path.rglob("*")
            if file.is_file()
        }
    )
    return {
        name: found[name].read_bytes().replace(b"\r\n", b"\n") for name in sorted(found)
    }


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    for name, data in _files(path).items():
        digest.update(f"{name}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest()


def _same(left: Path, right: Path) -> bool:
    return left.exists() and right.exists() and _files(left) == _files(right)


def _remove(path: Path) -> None:
    """Delete a file, a directory, or a link without following it."""
    if path.is_junction():
        path.rmdir()
    elif path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _replace(source: Path, target: Path) -> None:
    _remove(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copyfile(source, target)


def _package_source(name: str, entry: Entry) -> Path:
    """Return the copy of a skill that an installed Python or npm package ships."""
    if package := entry.get("python"):
        spec = importlib.util.find_spec(package)
        if spec is None or spec.origin is None:
            raise SystemExit(f"{name}: {package} is not installed; run uv sync")
        source = Path(spec.origin).parent / ".agents" / "skills" / name
    else:
        if not (NODE_MODULES / entry["npm"]).is_dir():
            raise SystemExit(
                f"{name}: {entry['npm']} is not installed; run "
                "bun install --frozen-lockfile in frontend"
            )
        source = NODE_MODULES / entry["npm"] / entry["path"]
    if not source.exists():
        raise SystemExit(f"{name}: the installed package no longer ships {source}")
    return source


def _github(url: str, accept: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": accept})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _fetch(entry: Entry, target: Path) -> None:
    """Install the pinned commit's copy of a GitHub entry at *target*."""
    archive = _github(
        f"https://codeload.github.com/{entry['github']}/tar.gz/{entry['commit']}",
        "application/gzip",
    )
    wanted = PurePosixPath(entry["path"])
    with (
        tempfile.TemporaryDirectory() as scratch,
        tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar,
    ):
        members = [
            member
            for member in tar.getmembers()
            if PurePosixPath(*PurePosixPath(member.name).parts[1:]).is_relative_to(
                wanted
            )
        ]
        if not members:
            raise SystemExit(f"{entry['github']} has no {wanted} at {entry['commit']}")
        tar.extractall(scratch, members=members, filter="data")
        (top,) = Path(scratch).iterdir()
        _replace(top / wanted, target)


def _update(name: str, entry: Entry, target: Path) -> None:
    """Move a GitHub entry to the latest commit of its default branch."""
    commit = _github(
        f"https://api.github.com/repos/{entry['github']}/commits/HEAD",
        "application/vnd.github.sha",
    ).decode()
    if commit != entry.get("commit") or not target.exists():
        entry["commit"] = commit
        _fetch(entry, target)
        entry["sha256"] = _digest(target)
        print(f"{name}: {entry['github']}@{commit[:12]}")


def _install(name: str, entry: Entry, target: Path) -> None:
    if "github" in entry:
        if not target.exists() or _digest(target) != entry["sha256"]:
            _fetch(entry, target)
    elif "local" not in entry:
        source = _package_source(name, entry)
        if not _same(source, target):
            _replace(source, target)
    elif not target.is_dir():
        raise SystemExit(f"{name}: the local skill {target} is missing")


def _problem(name: str, entry: Entry, target: Path) -> str | None:
    """Describe how an installed entry differs from its source, if it does."""
    if not target.exists():
        return f"{name} is not installed"
    if "github" in entry:
        if _digest(target) != entry["sha256"]:
            return f"{name} differs from {entry['github']}@{entry['commit'][:12]}"
    elif "local" not in entry and not _same(_package_source(name, entry), target):
        return f"{name} differs from the copy its installed package ships"
    return None


def _unlisted(names: set[str]) -> list[Path]:
    return [
        path
        for directory in (SKILLS, CLAUDE_SKILLS)
        if directory.is_dir()
        for path in sorted(directory.iterdir())
        if path.name not in names
    ]


def _check(entries: list[tuple[str, Entry, Path]], names: set[str]) -> int:
    problems = [
        problem
        for name, entry, target in entries
        if (problem := _problem(name, entry, target))
    ]
    problems += [
        f"{name} differs between .agents/skills and .claude/skills"
        for name in sorted(names)
        if (SKILLS / name).exists() and not _same(SKILLS / name, CLAUDE_SKILLS / name)
    ]
    problems += [
        f"{path.relative_to(ROOT).as_posix()} is not listed in skills.json"
        for path in _unlisted(names)
    ]
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print("Run: uv run python -m scripts.sync_skills", file=sys.stderr)
        return 1
    print(f"All {len(entries)} skills and subagents match their sources.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify without writing")
    mode.add_argument(
        "--update",
        action="store_true",
        help="move GitHub entries to the latest commit of their default branch",
    )
    args = parser.parse_args()

    manifest: dict[str, dict[str, Entry]] = json.loads(MANIFEST.read_text("utf-8"))
    names = set(manifest["skills"])
    entries = [
        (name, entry, SKILLS / name) for name, entry in manifest["skills"].items()
    ] + [
        (name, entry, CLAUDE_AGENTS / f"{name}.md")
        for name, entry in manifest["agents"].items()
    ]
    if args.check:
        return _check(entries, names)

    for name, entry, target in entries:
        if args.update and "github" in entry:
            _update(name, entry, target)
        else:
            _install(name, entry, target)
    for path in _unlisted(names):
        _remove(path)
    for name in names:
        if not _same(SKILLS / name, CLAUDE_SKILLS / name):
            _replace(SKILLS / name, CLAUDE_SKILLS / name)
    if args.update:
        MANIFEST.write_text(
            json.dumps(manifest, indent=2) + "\n", "utf-8", newline="\n"
        )
    return _check(entries, names)


if __name__ == "__main__":
    raise SystemExit(main())
