"""AppSettings model - single-row table for user-configurable settings.

:class:`AppSettingsBase` is the one declaration of what a setting is, what it
defaults to, and what values it accepts. The table below turns it into
columns, the read schema inherits it, the update schema validates against it
and the frontend's defaults are generated from it.
"""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import CheckConstraint, Field, SQLModel
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...domain import (
    AspectRatioTolerance,
    AutoUnmonitor,
    TmdbLanguageFilter,
    Workflow,
)
lazy from ..columns import enum_columns, enum_type

#: The settings row is a singleton; pinning its key makes that a database rule
#: rather than a convention two concurrent writers could break.
SETTINGS_ROW_ID = 1

#: Longest accepted theme search template.
MAX_THEME_FORMAT_LENGTH = 200


class AppSettingsBase(SQLModel):
    """Every user-editable setting, with its default and accepted range.

    Choices publish closed enums in the API. CHECK constraints also enforce
    their allowed values in the database.
    """

    auto_match_art: bool = False
    workflow: Workflow = Field(default=Workflow.ART, sa_type=enum_type(Workflow))
    theme_search_format: str = Field(
        default="{title} {year} main theme music ost",
        min_length=1,
        max_length=MAX_THEME_FORMAT_LENGTH,
    )
    min_duration_seconds: int = Field(default=30, ge=0, le=3600)
    max_duration_seconds: int = Field(default=300, ge=0, le=3600)
    normalize_theme_loudness: bool = True
    skip_media_server_tmdb_urls: bool = False
    disable_media_server_art: bool = False
    aspect_ratio_tolerance: AspectRatioTolerance = Field(
        default=AspectRatioTolerance.STRICT, sa_type=enum_type(AspectRatioTolerance)
    )
    tmdb_language_filter: TmdbLanguageFilter = Field(
        default=TmdbLanguageFilter.EN_NULL, sa_type=enum_type(TmdbLanguageFilter)
    )
    auto_advance: bool = False
    auto_advance_skip_completed: bool = True
    auto_unmonitor: AutoUnmonitor = Field(
        default=AutoUnmonitor.OFF, sa_type=enum_type(AutoUnmonitor)
    )

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        """Return a mapping of all setting field names to their defaults."""
        return {name: field.default for name, field in cls.model_fields.items()}


class AppSettings(AppSettingsBase, table=True):
    """Store the single application settings row."""

    __tablename__: ClassVar[Any] = "app_settings"
    __table_args__ = (
        CheckConstraint(f"id = {SETTINGS_ROW_ID}", name="ck_app_settings_singleton"),
    )

    id: int = Field(default=SETTINGS_ROW_ID, primary_key=True)
    updated_at: datetime | None = None


enum_columns(AppSettings)


async def get_app_settings(session: AsyncSession) -> AppSettings:
    """Return the persisted settings row, or an unpersisted instance with defaults."""
    row = await session.get(AppSettings, SETTINGS_ROW_ID)
    if row is not None:
        return row
    return AppSettings()
