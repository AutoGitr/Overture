"""What a collection's criteria say about the titles its lists hold."""

lazy from overture.domain import FilterOperator, TmdbChart
lazy from overture.schemas.collections import (
    FilterGroup,
    RadarrTagSource,
    SourceCondition,
    TmdbChartSource,
)


def test_only_included_tmdb_and_mdblist_lists_can_hold_titles_the_library_lacks() -> (
    None
):
    chart = TmdbChartSource(chart=TmdbChart.POPULAR, limit=3)
    excluded = TmdbChartSource(chart=TmdbChart.TOP_RATED, limit=3)
    criteria = FilterGroup(
        conditions=[
            SourceCondition(source=chart),
            SourceCondition(source=RadarrTagSource(tags=["4k"])),
        ],
        groups=[
            FilterGroup(
                conditions=[
                    SourceCondition(source=excluded, operator=FilterOperator.IS_NOT)
                ]
            )
        ],
    )

    assert criteria.listing_sources() == [chart]
    assert FilterGroup().listing_sources() == []
