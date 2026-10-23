"""Application settings route-facing service operations."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from .. import protocols
lazy from ..config import Settings
lazy from ..db.models.settings import AppSettings, get_app_settings
lazy from ..db.session import Database
lazy from ..media_servers.registry import ProviderRegistry
lazy from ..schemas.settings import (
    AppSettingsRead,
    AppSettingsUpdate,
    ConnectivityStatusResponse,
)
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.time import utc_now
lazy from .downloads.collection_theme import collection_themes_unavailable
lazy from .health import get_service_status


def _read(
    settings_row: AppSettings,
    app_config: Settings,
    provider_registry: ProviderRegistry,
) -> AppSettingsRead:
    """Return the saved settings with the environment-derived extras."""
    collections = provider_registry.collections
    return AppSettingsRead.model_validate(settings_row).model_copy(
        update={
            "media_server": app_config.MEDIA_SERVER,
            "tmdb_configured": app_config.tmdb_configured,
            "collections_supported": collections is not None,
            "collection_themes_unavailable": collection_themes_unavailable(
                collections, app_config
            ),
            "art_download_workers": app_config.ART_DOWNLOAD_WORKERS,
            "theme_download_workers": app_config.THEME_DOWNLOAD_WORKERS,
        }
    )


async def get_settings(
    db: AsyncSession, *, app_config: Settings, provider_registry: ProviderRegistry
) -> AppSettingsRead:
    """Return current settings, falling back to defaults when unsaved.

    Reading does not write. Settings nobody has saved yet read as their
    defaults; the row appears when :func:`update_settings` saves one.
    """
    return _read(await get_app_settings(db), app_config, provider_registry)


async def update_settings(
    body: AppSettingsUpdate,
    *,
    app_config: Settings,
    database: Database,
    provider_registry: ProviderRegistry,
) -> AppSettingsRead:
    """Update persisted application settings.

    Only the fields the request actually sent are applied; the schema has
    already checked every value against the persisted model's ranges.
    """
    async with database.write_session() as db:
        settings_row = await get_app_settings(db)
        settings_row.sqlmodel_update(
            body.model_dump(exclude_unset=True, exclude_none=True)
        )

        if settings_row.min_duration_seconds > settings_row.max_duration_seconds:
            raise PublicServiceError(
                400,
                "min_duration_seconds must be less than or equal to "
                "max_duration_seconds",
            )

        settings_row.updated_at = utc_now()
        db.add(settings_row)

    return _read(settings_row, app_config, provider_registry)


async def check_connectivity(
    provider_registry: ProviderRegistry, tmdb_client: protocols.ConnectivityProbe
) -> ConnectivityStatusResponse:
    """Probe every external service and report which answer."""
    return await get_service_status(provider_registry, tmdb_client)
