"""Backup router - backups and their schedule."""

lazy from fastapi import status

lazy from ..dependencies import BackupsDep
lazy from ..schemas.backup import (
    BackupCreatedResponse,
    BackupListResponse,
    BackupScheduleResponse,
    BackupScheduleUpdate,
)
lazy from .auth import authenticated_router

router = authenticated_router(prefix="/backups", tags=["backups"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backup(backups: BackupsDep) -> BackupCreatedResponse:
    """Back the database up now."""
    return await backups.backup_now()


@router.get("")
def list_backups(backups: BackupsDep) -> BackupListResponse:
    """Return all existing backups, newest first."""
    return backups.list_backups()


@router.get("/schedule")
async def get_backup_schedule(backups: BackupsDep) -> BackupScheduleResponse:
    """Return the current backup schedule configuration."""
    return await backups.get_schedule()


@router.put("/schedule")
async def update_backup_schedule(
    body: BackupScheduleUpdate, backups: BackupsDep
) -> BackupScheduleResponse:
    """Update the backup schedule configuration."""
    return await backups.update_schedule(body)
