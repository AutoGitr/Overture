"""Notifications router - when runs are announced, and a test notification."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import NotificationsDep
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.notifications import (
    NotificationSettingsRead,
    NotificationSettingsUpdate,
)
lazy from .auth import require_auth

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_auth)],
)


@router.get("")
async def get_notifications(
    notifications: NotificationsDep,
) -> NotificationSettingsRead:
    """Return where notifications go and when each kind of run sends one."""
    return await notifications.get()


@router.put("")
async def update_notifications(
    body: NotificationSettingsUpdate, notifications: NotificationsDep
) -> NotificationSettingsRead:
    """Save when each kind of run sends a notification."""
    return await notifications.update(body)


@router.post("/test")
async def send_test_notification(notifications: NotificationsDep) -> StatusResponse:
    """Send a test notification to ``NOTIFY_URL``."""
    return await notifications.test()
