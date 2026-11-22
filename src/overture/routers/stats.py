"""Stats router - application metrics and storage statistics."""

lazy from ..dependencies import StatsDep
lazy from ..schemas.stats import StatsResponse
lazy from .auth import authenticated_router

router = authenticated_router(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(stats: StatsDep) -> StatsResponse:
    """Return aggregated totals, percentages, sizes, and database statistics."""
    return await stats.get_stats()
