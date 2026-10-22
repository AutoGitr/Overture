"""Stats router - application metrics and storage statistics."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import StatsDep
lazy from ..schemas.stats import StatsResponse
lazy from .auth import require_auth

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    dependencies=[Depends(require_auth)],
)


@router.get("")
async def get_stats(stats: StatsDep) -> StatsResponse:
    """Return aggregated totals, percentages, sizes, and database statistics."""
    return await stats.get_stats()
