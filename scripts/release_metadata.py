"""Validate or update release metadata and expose the canonical application version."""

lazy import argparse
lazy import json
lazy import re
lazy import tomllib
lazy from datetime import UTC, date, datetime
lazy from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The container image every release is published as.
IMAGE = "ghcr.io/autogitr/overture"
DOCKERHUB_IMAGE = "autogitr/overture"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHANGELOG = "CHANGELOG.md"
#: The change types Keep a Changelog groups a release's entries under.
CHANGE_TYPES = frozenset(
    {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}
)
REQUIRED_RELEASE_FILES = (
    CHANGELOG,
    ".github/README.md",
    ".github/SECURITY.md",
    ".github/SUPPORT.md",
    ".github/labels.json",
    "licenses/THIRD_PARTY_NOTICES.md",
)
_PYPROJECT_VERSION = re.compile(r'(?m)^version = "[^"]+"$')
_UV_LOCK_OVERTURE_VERSION = re.compile(r'(?m)^(name = "overture"\nversion = )"[^"]+"$')
_UNRELEASED = "Unreleased"
_CHANGELOG_SECTION = re.compile(r"(?m)^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?$")
_CHANGELOG_GROUP = re.compile(r"(?m)^### (.+)$")
_CHANGELOG_ENTRY = re.compile(r"(?m)^- \S")


def _parse_semver(value: object, *, label: str = "version") -> str:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError(f"{label} must be a stable semantic version")
    return value


def project_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as project_file:
        version = tomllib.load(project_file)["project"]["version"]
    return _parse_semver(version, label="project.version")


def _uv_lock_version(root: Path) -> str | None:
    with (root / "uv.lock").open("rb") as lock_file:
        packages = tomllib.load(lock_file).get("package", ())
    for package in packages:
        if package.get("name") == "overture":
            version = package.get("version")
            return version if isinstance(version, str) else None
    return None


def _frontend_version(root: Path) -> str | None:
    package = json.loads((root / "frontend" / "package.json").read_text())
    version = package.get("version")
    return version if isinstance(version, str) else None


def _openapi_version(root: Path) -> str | None:
    schema = json.loads((root / "openapi" / "overture.json").read_text())
    version = schema.get("info", {}).get("version")
    return version if isinstance(version, str) else None


def _changelog_sections(root: Path) -> dict[str, str]:
    """Return each changelog section's body by version, starting with Unreleased."""
    text = (root / CHANGELOG).read_text()
    matches = list(_CHANGELOG_SECTION.finditer(text))
    if not matches or matches[0].group(1) != _UNRELEASED or matches[0].group(2):
        raise ValueError(f"{CHANGELOG} must start with a ## [{_UNRELEASED}] section")
    ends = [match.start() for match in matches[1:]] + [len(text)]
    sections: dict[str, str] = {}
    for match, end in zip(matches, ends, strict=True):
        name, released = match.groups()
        if name in sections:
            raise ValueError(f"{CHANGELOG} has more than one {name} section")
        if name != _UNRELEASED:
            _parse_semver(name, label=f"{CHANGELOG} section {name!r}")
            if released is None:
                raise ValueError(f"{CHANGELOG} section {name} has no release date")
        body = text[match.end() : end].strip()
        unknown = set(_CHANGELOG_GROUP.findall(body)) - CHANGE_TYPES
        if unknown:
            raise ValueError(
                f"{CHANGELOG} section {name} has unknown change types: "
                + ", ".join(sorted(unknown))
            )
        sections[name] = body
    return sections


def release_notes(version: str, root: Path = ROOT) -> str:
    notes = _changelog_sections(root).get(version, "")
    if not _CHANGELOG_ENTRY.search(notes):
        raise ValueError(f"{CHANGELOG} has no entries for {version}")
    return f"{notes}\n"


def validate_release(root: Path = ROOT, *, tag: str | None = None) -> str:
    version = project_version(root)
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match project version v{version}")

    missing = [name for name in REQUIRED_RELEASE_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError("missing release files: " + ", ".join(missing))
    if tag is None:
        _changelog_sections(root)
    else:
        release_notes(version, root)

    for label, actual in (
        ("frontend/package.json", _frontend_version(root)),
        ("uv.lock", _uv_lock_version(root)),
        ("openapi/overture.json", _openapi_version(root)),
    ):
        if actual != version:
            raise ValueError(
                f"{label} version {actual!r} does not match project version {version}"
            )
    return version


def prepare_release(raw_version: str, root: Path = ROOT, *, today: date) -> str:
    """Set the version everywhere and move the unreleased changes under it."""
    version = _parse_semver(raw_version.removeprefix("v"))
    sections = _changelog_sections(root)
    if version in sections:
        raise ValueError(f"{CHANGELOG} already has a {version} section")
    if not _CHANGELOG_ENTRY.search(sections[_UNRELEASED]):
        raise ValueError(f"{CHANGELOG} has no unreleased entries")
    changelog_path = root / CHANGELOG
    heading = f"## [{_UNRELEASED}]"
    changelog_path.write_text(
        changelog_path.read_text().replace(
            heading, f"{heading}\n\n## [{version}] - {today.isoformat()}", 1
        ),
        newline="\n",
    )

    pyproject_path = root / "pyproject.toml"
    pyproject_text, count = _PYPROJECT_VERSION.subn(
        f'version = "{version}"', pyproject_path.read_text(), count=1
    )
    if count != 1:
        raise ValueError("pyproject.toml does not contain a unique version line")
    pyproject_path.write_text(pyproject_text, newline="\n")

    uv_lock_path = root / "uv.lock"
    uv_lock_text, count = _UV_LOCK_OVERTURE_VERSION.subn(
        rf'\1"{version}"', uv_lock_path.read_text(), count=1
    )
    if count != 1:
        raise ValueError("uv.lock does not contain an overture package entry")
    uv_lock_path.write_text(uv_lock_text, newline="\n")

    package_json_path = root / "frontend" / "package.json"
    package_json = json.loads(package_json_path.read_text())
    package_json["version"] = version
    package_json_path.write_text(
        f"{json.dumps(package_json, indent=2)}\n", newline="\n"
    )

    openapi_path = root / "openapi" / "overture.json"
    openapi = json.loads(openapi_path.read_text())
    openapi["info"]["version"] = version
    openapi_path.write_text(
        f"{json.dumps(openapi, sort_keys=True, indent=2)}\n", newline="\n"
    )

    return validate_release(root, tag=f"v{version}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare",
        metavar="VERSION",
        help="Set the version and release the unreleased changelog entries.",
    )
    parser.add_argument("--tag")
    parser.add_argument(
        "--notes-file", type=Path, help="Write the tag's changelog section here."
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    if args.notes_file and args.tag is None:
        parser.error("--notes-file requires --tag")
    try:
        if args.prepare is not None:
            prepare_release(args.prepare, today=datetime.now(UTC).date())
        version = validate_release(tag=args.tag)
        if args.notes_file:
            args.notes_file.write_text(release_notes(version), newline="\n")
    except (KeyError, OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        parser.error(str(exc))
    print(version)
    if args.github_output:
        with args.github_output.open("a", newline="\n") as output:
            output.write(f"version={version}\n")
            output.write(f"image={IMAGE}\n")
            output.write(f"dockerhub_image={DOCKERHUB_IMAGE}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
