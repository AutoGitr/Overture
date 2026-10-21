"""Settings router - get, update, connectivity test."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import (
    DatabaseDep,
    ProviderRegistryDep,
    SessionDep,
    SettingsDep,
    TmdbDep,
)
lazy from ..schemas.settings import (
    AppSettingsRead,
    AppSettingsUpdate,
    ConnectivityStatusResponse,
)
lazy from ..services import settings as settings_service
lazy from .auth import require_auth

router = APIRouter(
    prefix="/settings", tags=["settings"], dependencies=[Depends(require_auth)]
)


@router.get("")
async def get_settings(db: SessionDep, settings: SettingsDep) -> AppSettingsRead:
    """Return current settings."""
    return await settings_service.get_settings(db, app_config=settings)


@router.put("")
async def update_settings(
    body: AppSettingsUpdate, settings: SettingsDep, database: DatabaseDep
) -> AppSettingsRead:
    """Update settings."""
    return await settings_service.update_settings(
        body, app_config=settings, database=database
    )


@router.get("/connectivity")
async def check_connectivity(
    providers: ProviderRegistryDep, tmdb: TmdbDep
) -> ConnectivityStatusResponse:
    """Probe every external service and report which are reachable."""
    return await settings_service.check_connectivity(providers, tmdb)
