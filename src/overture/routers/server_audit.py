"""Server Audit router - compare local assets against media-server state."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import AuditDep
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.server_audit import (
    FixAuditRequest,
    ServerAuditRequest,
)
lazy from .auth import require_auth

router = APIRouter(
    prefix="/server-audit",
    tags=["server-audit"],
    dependencies=[Depends(require_auth)],
)


@router.post("/scan")
async def start_server_audit(
    body: ServerAuditRequest,
    audit: AuditDep,
) -> StatusResponse:
    """Start an audit comparing local assets to current media-server assets."""
    return await audit.start(body)


@router.post("/scan/stop")
async def stop_server_audit(audit: AuditDep) -> StatusResponse:
    """Stop a running server audit."""
    return audit.stop()


@router.post("/fix")
async def fix_audit_findings(
    body: FixAuditRequest,
    audit: AuditDep,
) -> StatusResponse:
    """Start fixing selected findings, then verify each one.

    Images are unlocked and refreshed; themes have their server theme deleted
    before their item is refreshed.
    """
    return await audit.fix(body)


@router.post("/fix/stop")
async def stop_audit_fix(audit: AuditDep) -> StatusResponse:
    """Stop fixing audit findings."""
    return audit.stop_fix()
