"""Settings REST and WebSocket schemas."""

lazy from datetime import datetime
lazy from typing import Self

lazy from pydantic import model_validator
lazy from sqlmodel._compat import SQLModelConfig

lazy from ..db.models.settings import AppSettingsBase
lazy from ..domain import (
    AspectRatioTolerance,
    AutoUnmonitor,
    ServerType,
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

    auto_match_art: bool | None = None
    workflow: Workflow | None = None
    theme_search_format: str | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    normalize_theme_loudness: bool | None = None
    skip_media_server_tmdb_urls: bool | None = None
    disable_media_server_art: bool | None = None
    aspect_ratio_tolerance: AspectRatioTolerance | None = None
    plex_collections_enabled: bool | None = None
    tmdb_language_filter: TmdbLanguageFilter | None = None
    auto_advance: bool | None = None
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
