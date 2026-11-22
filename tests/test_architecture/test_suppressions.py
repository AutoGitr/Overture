"""Every suppressed check says why it does not apply.

A suppression names its rule and its reason, after ``--`` on the line or in
a comment directly above the lines it covers, so a reader can tell whether
it still holds. Generated code, which no one edits, is left out.
"""

lazy import re
lazy from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: The suppressions of Ruff, Pyright, ESLint, TypeScript and Svelte.
SUPPRESSION = re.compile(
    r"#\s*noqa\b|#\s*pyright:\s*ignore|eslint-disable|@ts-(?:expect-error|ignore)"
    r"|svelte-ignore"
)
SOURCES = {
    "src/overture": "*.py",
    "scripts": "*.py",
    "tests": "*.py",
    "typings": "*.pyi",
    "frontend/src": "*.[ts][sv]*",
    "frontend/scripts": "*.ts",
}
GENERATED = ("frontend/src/generated/", "src/overture/frontend/")
COMMENT = ("#", "//", "/*", "*", "<!--")


def _unexplained(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    found: list[str] = []
    for number, line in enumerate(lines):
        match = SUPPRESSION.search(line)
        if match is None or " -- " in line[match.start() :]:
            continue
        above = number - 1
        # A reason above a run of suppressed lines, blank lines between
        # import groups included, covers each of them.
        while above >= 0 and (
            SUPPRESSION.search(lines[above])
            or (not lines[above].strip() and SUPPRESSION.search(lines[above - 1]))
        ):
            above -= 1
        if above < 0 or not lines[above].strip().startswith(COMMENT):
            found.append(f"{path.relative_to(ROOT)}:{number + 1}")
    return found


def test_every_suppression_says_why() -> None:
    paths = [
        path
        for folder, pattern in SOURCES.items()
        for path in (ROOT / folder).rglob(pattern)
        if path.suffix in {".py", ".pyi", ".ts", ".svelte", ".js"}
        and not str(path.relative_to(ROOT)).startswith(GENERATED)
        # This file names the suppressions it looks for.
        and path != Path(__file__).resolve()
    ]
    assert len(paths) > 500
    unexplained = [line for path in paths for line in _unexplained(path)]
    assert unexplained == [], "Say why after `--`, or in a comment above"
