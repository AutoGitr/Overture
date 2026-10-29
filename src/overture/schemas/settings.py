"""Settings REST and WebSocket schemas."""

lazy from datetime import datetime
lazy from typing import Self

lazy from pydantic import model_validator
lazy from sqlmodel._compat import SQLModelConfig

lazy from ..db.models.settings import AppSettingsBase
lazy from ..domain import (
    AspectRatioTolerance,
    AutoAdvance,
    AutoUnmonitor,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    ServerType,
    SyncMode,
    TmdbLanguageFilter,
    Workflow,
)
lazy from .base import StrictBaseModel


class AppSettingsRead(AppSettingsBase):
    """Schema for reading settings.

    The persisted fields come from :class:`AppSettingsBase`; only the
    environment-derived extras are declared here.
    """

    model_config = SQLModelConfig(
        extra="forbid",
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
    )

    updated_at: datetime | None = None
    media_server: ServerType | None = None
    tmdb_configured: bool = False
    mdblist_configured: bool = False
    radarr_configured: bool = False
    sonarr_configured: bool = False
    #: The media server has collections Overture can manage.
    collections_supported: bool = False
    #: Why collection themes cannot be stored, when they cannot.
    collection_themes_unavailable: str | None = None
    art_download_workers: int = 1
    theme_download_workers: int = 1


class ConnectivityStatusResponse(StrictBaseModel):
    """Whether the configured media server and TMDB answer."""

    media_server: bool
    tmdb: bool


class AppSettingsUpdate(StrictBaseModel):
    """Schema for updating settings.

    Every field of :class:`AppSettingsBase` is here as optional: only the ones
    a request actually sends are applied, which is what
    ``model_dump(exclude_unset=True)`` gives the service. Ranges are validated
    against the persisted model's own declarations, and a test keeps the two
    field lists equal.
    """

    collection_sync_mode: SyncMode | None = None
    collection_mode_default: CollectionMode | None = None
    collection_order_default: CollectionOrder | None = None
    collection_filtering_default: CollectionFiltering | None = None
    collection_visible_home: bool | None = None
    collection_visible_shared: bool | None = None
    collection_visible_library: bool | None = None
    collection_minimum_items: int | None = None
    collection_delete_below_minimum: bool | None = None
    collection_auto_match_art: bool | None = None
    collection_auto_match_theme: bool | None = None
    collection_sort_title_format: str | None = None
    collection_summary_format: str | None = None
    collection_delete_when_inactive: bool | None = None
    collection_sync_schedule: str | None = None
    collection_sync_enabled: bool | None = None
    collection_request_missing: bool | None = None
    collection_import_unmanaged: bool | None = None
    collection_require_group: bool | None = None
    overturedb_no_theme: bool | None = None
    overturedb_browse: bool | None = None
    tmdb_region: str | None = None
    radarr_root_folder: str | None = None
    radarr_quality_profile_id: int | None = None
    radarr_search: bool | None = None
    sonarr_root_folder: str | None = None
    sonarr_quality_profile_id: int | None = None
    sonarr_search: bool | None = None
    auto_match_art: bool | None = None
    workflow: Workflow | None = None
    theme_search_format: str | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    normalize_theme_loudness: bool | None = None
    skip_media_server_tmdb_urls: bool | None = None
    disable_media_server_art: bool | None = None
    aspect_ratio_tolerance: AspectRatioTolerance | None = None
    tmdb_language_filter: TmdbLanguageFilter | None = None
    auto_advance: AutoAdvance | None = None
    auto_advance_skip_completed: bool | None = None
    auto_unmonitor: AutoUnmonitor | None = None

    @model_validator(mode="after")
    def validate_against_persisted_fields(self) -> Self:
        """Reject values the persisted model would not accept.

        Running the supplied fields through :class:`AppSettingsBase` reuses
        its ranges and lengths instead of restating them here. Rules that
        span fields need the saved values too, so the service checks those.

        Returns:
            The validated update.
        """
        AppSettingsBase.model_validate(self.model_dump(exclude_none=True))
        return self
