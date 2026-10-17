"""Validate or update release metadata and expose the canonical application version."""

lazy import argparse
lazy import json
lazy import re
lazy import tomllib
lazy from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The container image every release is published as.
IMAGE = "ghcr.io/autogitr/overture"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
REQUIRED_RELEASE_FILES = (
    ".github/README.md",
    ".github/SECURITY.md",
    ".github/SUPPORT.md",
    ".github/labels.json",
    ".github/release.yml",
    "licenses/THIRD_PARTY_NOTICES.md",
)
_PYPROJECT_VERSION = re.compile(r'(?m)^version = "[^"]+"$')
_UV_LOCK_OVERTURE_VERSION = re.compile(r'(?m)^(name = "overture"\nversion = )"[^"]+"$')


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


def validate_release(root: Path = ROOT, *, tag: str | None = None) -> str:
    version = project_version(root)
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match project version v{version}")

    missing = [name for name in REQUIRED_RELEASE_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError("missing release files: " + ", ".join(missing))

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


def set_release_version(raw_version: str, root: Path = ROOT) -> str:
    version = _parse_semver(raw_version.removeprefix("v"))

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

    return validate_release(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", metavar="VERSION", help="Set the release version.")
    parser.add_argument("--tag")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        if args.set is not None:
            set_release_version(args.set)
        version = validate_release(tag=args.tag)
    except (KeyError, OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        parser.error(str(exc))
    print(version)
    if args.github_output:
        with args.github_output.open("a", newline="\n") as output:
            output.write(f"version={version}\n")
            output.write(f"image={IMAGE}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
