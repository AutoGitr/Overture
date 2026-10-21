"""Every place that describes Overture uses the project description."""

lazy import re
lazy import tomllib
lazy from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_META_DESCRIPTION = re.compile(
    r'(?:name|property)="(?:\w+:)?description"\s+content="([^"]+)"'
)


def test_image_readme_and_web_app_use_the_project_description() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        description = tomllib.load(project_file)["project"]["description"]

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f'org.opencontainers.image.description="{description}"' in dockerfile
    assert f"\n_{description}_\n" in (ROOT / ".github/README.md").read_text()
    assert (
        f'description: "{description}",'
        in (ROOT / "frontend/vite.config.ts").read_text()
    )
    index = (ROOT / "frontend/index.html").read_text()
    assert _META_DESCRIPTION.findall(index) == [description] * 3
