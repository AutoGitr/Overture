"""The docs list every variable Overture reads at start, with its default.

``Settings`` is where a variable is defined; the docs are where people read
about it. A variable added, renamed or given another default in one and not
the other fails here.
"""

lazy import re
lazy from pathlib import Path

lazy from pydantic import SecretStr

lazy from overture.config import MediaServerConfig, Settings

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/overture/install"
#: The pages that document variables, and the one the defaults of its rows
#: belong to: the Linux service documents its own paths' defaults.
PAGES = ("environment-variables.md", "linux-service.md")
#: Read before Settings exists, to find the file Settings is read from.
READ_FIRST = {"OVERTURE_CONFIG_FILE"}
_ROW = re.compile(r"^\| `([A-Z_<>]+)`\s*\|[^|]*\|\s*([^|]*?)\s*\|", re.MULTILINE)


def _documented(page: str) -> dict[str, str]:
    """Each variable a page's tables document, with its Default column."""
    return dict(_ROW.findall((DOCS / page).read_text()))


def _read() -> set[str]:
    per_server = {
        f"MEDIA_SERVER_<NAME>_{field.upper()}"
        for field in MediaServerConfig.model_fields
        if field != "name"
    }
    return set(Settings.model_fields) | per_server | READ_FIRST


def test_every_variable_read_is_documented_and_every_one_documented_is_read() -> None:
    documented = set[str]().union(*(_documented(page) for page in PAGES))
    assert documented == _read()


def test_documented_defaults_are_the_ones_settings_use() -> None:
    documented = _documented("environment-variables.md")
    for name, field in Settings.model_fields.items():
        if name not in documented:
            continue
        default = field.default
        if isinstance(default, SecretStr):
            default = default.get_secret_value()
        expected = (
            str(default).lower()
            if isinstance(default, bool)
            else ""
            if default in ("", None, ())
            else str(default)
        )
        shown = re.match(r"`([^`]*)`", documented[name])
        assert (shown.group(1) if shown else "") == expected, name
