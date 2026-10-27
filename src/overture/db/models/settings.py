"""AppSettings model - single-row table for user-configurable settings.

:class:`AppSettingsBase` is the one declaration of what a setting is, what it
defaults to, and what values it accepts. The table below turns it into
columns, the read schema inherits it, the update schema validates against it
and the frontend's defaults are generated from it.
"""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from pydantic import field_validator
lazy from sqlmodel import CheckConstraint, Field, SQLModel
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...domain import (
    AspectRatioTolerance,
    AutoUnmonitor,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    SyncMode,
    TmdbLanguageFilter,
    Workflow,
)
lazy from ...utils.collection_formats import (
    validate_sort_title_format,
    validate_summary_format,
)
lazy from ...utils.cron import validate_cron_expression
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

    collection_sync_mode: SyncMode = Field(
        default=SyncMode.SYNC, sa_type=enum_type(SyncMode)
    )
    collection_mode_default: CollectionMode = Field(
        default=CollectionMode.DEFAULT, sa_type=enum_type(CollectionMode)
    )
    collection_order_default: CollectionOrder = Field(
        default=CollectionOrder.RELEASE_ASC, sa_type=enum_type(CollectionOrder)
    )
    collection_filtering_default: CollectionFiltering = Field(
        default=CollectionFiltering.ADMIN, sa_type=enum_type(CollectionFiltering)
    )
    collection_visible_home: bool = False
    collection_visible_shared: bool = False
    collection_visible_library: bool = False
    collection_minimum_items: int = Field(default=1, ge=1, le=100)
    collection_delete_below_minimum: bool = False
    collection_auto_match_art: bool = False
    collection_auto_match_theme: bool = False
    collection_sort_title_format: str = Field(default="", max_length=200)
    collection_summary_format: str = Field(default="", max_length=2000)
    collection_delete_when_inactive: bool = False
    collection_sync_schedule: str = Field(default="0 3 * * *", max_length=100)
    collection_sync_enabled: bool = True
    collection_request_missing: bool = False
    collection_import_unmanaged: bool = True
    #: The country whose charts and streaming services TMDB reports.
    tmdb_region: str = Field(default="US", min_length=2, max_length=2)
    radarr_root_folder: str = Field(default="", max_length=500)
    radarr_quality_profile_id: int | None = Field(default=None, ge=1)
    radarr_search: bool = True
    sonarr_root_folder: str = Field(default="", max_length=500)
    sonarr_quality_profile_id: int | None = Field(default=None, ge=1)
    sonarr_search: bool = True
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

    @field_validator("collection_sort_title_format")
    @classmethod
    def valid_collection_sort_title_format(cls, value: str) -> str:
        """Use the same template syntax as generators and bulk operations."""
        return validate_sort_title_format(value)

    @field_validator("collection_sync_schedule")
    @classmethod
    def valid_collection_sync_schedule(cls, value: str) -> str:
        """Collections share the cron syntax of every other schedule."""
        return validate_cron_expression(value)

    @field_validator("tmdb_region")
    @classmethod
    def valid_tmdb_region(cls, value: str) -> str:
        """TMDB names regions by ISO 3166-1 code."""
        if not value.isascii() or not value.isalpha():
            raise ValueError("Use a two-letter country code, such as US")
        return value.upper()

    @field_validator("collection_summary_format")
    @classmethod
    def valid_collection_summary_format(cls, value: str) -> str:
        """Use the same summary template syntax across all policy tiers."""
        return validate_summary_format(value)

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
