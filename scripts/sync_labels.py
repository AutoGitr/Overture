"""Reconcile all repository labels with labels.json; preview unless --apply."""

lazy import argparse
lazy import json
lazy import re
lazy import shutil
lazy import subprocess
lazy import sys
lazy from pathlib import Path
lazy from typing import Any, TypedDict
lazy from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


class Label(TypedDict, closed=True):
    name: str
    color: str
    description: str


def gh(*args: str, payload: dict[str, Any] | None = None) -> str:
    resolved = shutil.which("gh")
    if resolved is None:
        raise OSError("gh is required")
    stdin = None if payload is None else json.dumps(payload)
    extra = () if payload is None else ("--input", "-")
    result = subprocess.run(
        [resolved, *args, *extra],
        cwd=ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return result.stdout.strip()


def api(
    path: str, payload: dict[str, Any] | None = None, *, method: str | None = None
) -> Any:
    """Call a GitHub REST endpoint and return its JSON, or ``None`` if empty."""
    output = gh("api", path, *(("--method", method) if method else ()), payload=payload)
    return json.loads(output) if output else None


def pages(path: str) -> list[dict[str, Any]]:
    result: list[list[dict[str, Any]]] = json.loads(
        gh("api", path, "--paginate", "--slurp")
    )
    return [item for page in result for item in page]


def load_labels(root: Path = ROOT) -> list[Label]:
    labels: list[Label] = json.loads((root / ".github/labels.json").read_text())
    names: set[str] = set()
    for label in labels:
        if not re.fullmatch(r"[0-9a-f]{6}", label["color"]):
            raise ValueError(f"Invalid color for {label['name']}")
        if not label["description"] or len(label["description"]) > 100:
            raise ValueError(f"Invalid description for {label['name']}")
        name = label["name"]
        if not name or name != name.strip() or name.casefold() in names:
            raise ValueError(f"Empty, ambiguous or duplicate label: {name!r}")
        names.add(name.casefold())
    if not labels:
        raise ValueError("The label manifest must not be empty")
    return labels


def sync(repo: str, labels: list[Label], *, apply: bool) -> bool:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Repository must be OWNER/REPO")
    base = f"repos/{repo}"
    existing = {item["name"]: item for item in pages(f"{base}/labels?per_page=100")}
    changed = False
    for label in labels:
        name = label["name"]
        fields = {
            "name": name,
            "color": label["color"],
            "description": label["description"],
        }
        current = existing.get(name)
        if current is None or any(
            current[key] != value for key, value in fields.items()
        ):
            changed = True
            print(f"{'Create' if current is None else 'Update'} {name}")
            if apply:
                if current is None:
                    api(f"{base}/labels", fields, method="POST")
                else:
                    api(
                        f"{base}/labels/{quote(name, safe='')}",
                        {
                            "new_name": name,
                            "color": label["color"],
                            "description": label["description"],
                        },
                        method="PATCH",
                    )
    for name in sorted(existing.keys() - {label["name"] for label in labels}):
        changed = True
        print(f"Delete {name}")
        if apply:
            api(f"{base}/labels/{quote(name, safe='')}", method="DELETE")
    if not changed:
        print("Labels match labels.json.")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="AutoGitr/Overture")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true", help="Exit 1 if labels differ")
    args = parser.parse_args()
    try:
        changed = sync(args.repo, load_labels(), apply=args.apply)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Label synchronization failed: {exc}", file=sys.stderr)
        return 1
    return int(args.check and changed)


if __name__ == "__main__":
    raise SystemExit(main())
