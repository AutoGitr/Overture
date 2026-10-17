"""Assemble the Linux archive: python-build-standalone, Overture and its tools."""

lazy import argparse
lazy import hashlib
lazy import platform
lazy import re
lazy import shutil
lazy import subprocess
lazy import tarfile
lazy import tempfile
lazy from importlib.metadata import version
lazy from pathlib import Path

#: The oldest glibc the archive runs on. Wheels are chosen for it, and the build
#: fails if any bundled binary needs a newer one.
GLIBC_MINIMUM = (2, 28)
#: Where the Dockerfile copies this directory's files, the tools and the licenses.
SOURCE = Path(__file__).parent
_GLIBC_SYMBOL = re.compile(rb"GLIBC_(\d+)\.(\d+)")


def run(*command: str | Path, cwd: Path | None = None) -> str:
    """Run a build command, returning its output and letting errors show."""
    return subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def install_runtime(runtime: Path, project: Path, work: Path) -> None:
    """Install a relocatable interpreter, then the locked packages and Overture."""
    run("uv", "python", "install", "--install-dir", work, platform.python_version())
    (interpreter,) = (
        path
        for path in work.iterdir()
        if path.name.startswith("cpython-") and not path.is_symlink()
    )
    shutil.copytree(interpreter, runtime, symlinks=True)
    python = runtime / "bin/python3"
    site = run(python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))")
    requirements = work / "requirements.txt"
    run(
        "uv",
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--output-file",
        requirements,
        cwd=project,
    )
    run("uv", "build", "--wheel", "--out-dir", work / "wheel", cwd=project)
    install = (
        "uv",
        "pip",
        "install",
        "--python",
        python,
        "--target",
        site,
        "--python-platform",
        "x86_64-manylinux_{}_{}".format(*GLIBC_MINIMUM),
    )
    run(*install, "--requirement", requirements)
    run(*install, "--no-deps", *(work / "wheel").glob("*.whl"))


def required_glibc(bundle: Path) -> tuple[int, int]:
    """Return the newest glibc symbol version any bundled binary links against."""
    newest = (2, 0)
    for path in bundle.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        # Static binaries have no dynamic symbols, and objdump says so on stderr.
        symbols = subprocess.run(
            ["objdump", "-T", str(path)], capture_output=True, check=False
        ).stdout
        for match in _GLIBC_SYMBOL.finditer(symbols):
            newest = max(newest, (int(match[1]), int(match[2])))
    return newest


def build(project: Path, output: Path) -> Path:
    """Create the bundle, check its glibc floor and write the checksummed archive."""
    bundle = output / f"overture-{version('overture')}-linux-x86_64"
    with tempfile.TemporaryDirectory() as work:
        install_runtime(bundle / "runtime", project, Path(work))
    shutil.copytree(SOURCE / "tools", bundle / "tools")
    shutil.copytree(SOURCE / "licenses", bundle / "licenses")
    (bundle / "bin").mkdir()
    shutil.copy2(project / ".github/README.md", bundle / "README.md")
    for source, target in (
        ("overture", "bin/overture"),
        ("python", "bin/python"),
        ("install.sh", "install.sh"),
        ("uninstall.sh", "uninstall.sh"),
        ("overture.service", "overture.service"),
    ):
        shutil.copy2(SOURCE / source, bundle / target)
        (bundle / target).chmod(0o755 if target.startswith("bin/") else 0o644)
    needed = required_glibc(bundle)
    if needed > GLIBC_MINIMUM:
        raise SystemExit(
            "Bundled binaries need glibc {}.{}, newer than the supported {}.{}.".format(
                *needed, *GLIBC_MINIMUM
            )
        )
    (bundle / "glibc-minimum").write_text("{}.{}\n".format(*GLIBC_MINIMUM))
    run(bundle / "bin/overture", "--version")
    archive = output / f"{bundle.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(bundle, arcname=bundle.name)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    shutil.rmtree(bundle)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    print(build(arguments.project, arguments.output))
