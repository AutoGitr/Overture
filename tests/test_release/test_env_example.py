"""The example environment file offers every setting an installation sets."""

lazy import re
lazy from pathlib import Path

lazy from overture.config import Settings

ROOT = Path(__file__).resolve().parents[2]
#: Settings the container image and the native service set themselves.
SET_BY_THE_INSTALL = frozenset(
    {"OVERTURE_CONFIG_DIR", "OVERTURE_HOST", "OVERTURE_PORT"}
)


def test_every_setting_is_in_the_example_environment() -> None:
    example = (ROOT / ".env.example").read_text("utf-8")
    listed = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))
    settings = {name for name in Settings.model_fields if name.isupper()}
    assert settings - SET_BY_THE_INSTALL - listed == set()
    assert listed - settings == set()
