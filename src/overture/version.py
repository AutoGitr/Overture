"""Application version sourced from the project metadata."""

lazy from importlib.metadata import version
lazy from typing import Final

APP_VERSION: Final = version("overture")
