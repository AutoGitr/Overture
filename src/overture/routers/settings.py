"""Settings router - get, update, connectivity test."""

lazy from ..dependencies import (
    DatabaseDep,
    NeedsDep,
    ProviderRegistryDep,
    SettingsDep,
    TmdbDep,
)
lazy from ..schemas.settings import (
    AppSettingsRead,
    AppSettingsUpdate,
    ConnectivityStatusResponse,
)
lazy from ..services import settings as settings_service
lazy from .auth import authenticated_router

router = authenticated_router(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings(
    database: DatabaseDep, settings: SettingsDep, providers: ProviderRegistryDep
) -> AppSettingsRead:
    """Return current settings."""
    return await settings_service.get_settings(
        database=database, app_config=settings, provider_registry=providers
    )


@router.put("")
async def update_settings(
    body: AppSettingsUpdate,
    settings: SettingsDep,
    database: DatabaseDep,
    providers: ProviderRegistryDep,
    needs: NeedsDep,
) -> AppSettingsRead:
    """Update settings."""
    return await settings_service.update_settings(
        body,
        app_config=settings,
        database=database,
        provider_registry=providers,
        needs=needs,
    )


@router.get("/connectivity")
async def check_connectivity(
    providers: ProviderRegistryDep, tmdb: TmdbDep
) -> ConnectivityStatusResponse:
    """Probe every external service and report which are reachable."""
    return await settings_service.check_connectivity(providers, tmdb)
