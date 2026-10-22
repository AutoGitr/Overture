"""Links between the repository's documents point at files and headings that exist."""

lazy import re
lazy from pathlib import Path

lazy import pytest

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "https://github.com/AutoGitr/Overture"
DOCUMENTS = sorted(
    [
        *ROOT.glob("*.md"),
        *(ROOT / ".github").rglob("*.md"),
        *(ROOT / ".github").rglob("*.yml"),
        ROOT / "Dockerfile",
        ROOT / "compose.yaml",
    ]
)
_MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
_REPOSITORY_LINK = re.compile(
    rf"(?:{REPOSITORY}/blob/main/|https://raw\.githubusercontent\.com/AutoGitr/Overture/main/)"
    r"([^\s)#?\"'>]+)(?:#([\w-]+))?"
)
_README_ANCHOR = re.compile(rf"{REPOSITORY}#([\w-]+)")


def _anchors(path: Path) -> set[str]:
    """GitHub's heading ids for a Markdown file."""
    headings = re.findall(r"(?m)^#{1,6} (.+)$", path.read_text())
    return {
        re.sub(
            r"[^\w\- ]", "", re.sub(r"<[^>]+>|`", "", heading).strip().lower()
        ).replace(" ", "-")
        for heading in headings
    } | {"readme"}


def _assert_target(path: Path, anchor: str | None) -> None:
    assert path.exists(), path
    if anchor and path.suffix == ".md":
        assert anchor in _anchors(path), f"{path}#{anchor}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_document_links_resolve(document: Path) -> None:
    text = document.read_text()
    if document.suffix == ".md":
        for target in _MARKDOWN_LINK.findall(text):
            if re.match(r"[a-z]+:", target):
                continue
            file_part, _, anchor = target.partition("#")
            _assert_target(
                (document.parent / file_part).resolve() if file_part else document,
                anchor,
            )
    for file_part, anchor in _REPOSITORY_LINK.findall(text):
        _assert_target(ROOT / file_part, anchor)
    for anchor in _README_ANCHOR.findall(text):
        _assert_target(ROOT / ".github/README.md", anchor)
