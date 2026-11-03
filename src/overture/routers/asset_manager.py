"""Asset Renamer router - scan and rename misnamed art and theme files."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import AssetManagerDep
lazy from ..schemas.asset_manager import AssetRenameResponse, RenameRequest, ScanRequest
lazy from ..schemas.common import StatusResponse
lazy from .auth import require_auth

router = APIRouter(
    prefix="/asset-manager",
    tags=["asset-manager"],
    dependencies=[Depends(require_auth)],
)


@router.post("/scan")
async def start_scan(
    body: ScanRequest,
    asset_mgr: AssetManagerDep,
) -> StatusResponse:
    """Start an asset scan in the background."""
    return await asset_mgr.start_scan(body)


@router.post("/scan/stop")
async def stop_scan(asset_mgr: AssetManagerDep) -> StatusResponse:
    """Stop a running asset scan."""
    return asset_mgr.stop_scan()


@router.post("/rename")
async def rename_assets(
    body: RenameRequest,
    asset_mgr: AssetManagerDep,
) -> AssetRenameResponse:
    """Rename a list of files. Never overwrites existing targets."""
    return await asset_mgr.rename_assets(body)
