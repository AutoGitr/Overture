"""Coverage for planning out bulk targets OvertureDB cannot serve."""

lazy from datetime import timedelta
lazy from typing import Any

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.catalog import CatalogItemSeason
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    CURRENT_SELECTION,
    ArtBulkSource,
    ArtType,
    JobStatus,
    JobType,
    MediaType,
    RecentUnit,
    ServerAsset,
    ThemeBulkSource,
)
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.services.asset_runs.plan import (
    KEPT_IN_PLACE,
    SAVED_SELECTION,
    AssetPlan,
    Slot,
    plan_run,
)
lazy from overture.services.asset_runs.support import CheckedStamper
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import disable_catalog, enable_catalog
lazy from tests.factories import (
    CatalogItemFactory,
    MediaItemFactory,
    SeasonFactory,
    seed_theme,
)
lazy from tests.runtime_helpers import row_id

NO_ENTRY = (JobOutcome.NO_MATCH, "OvertureDB has no entry for it")
DISABLED = (JobOutcome.SKIPPED, "OvertureDB is disabled")
#: The stored facts of a slot's file on disk.
RECORDED = {"file_hash": "recorded", "file_mtime_ns": 1, "file_size": 1}


def no_art(art_type: ArtType) -> tuple[JobOutcome, str]:
    """Return the planned outcome of a slot an OvertureDB entry lacks."""
    return JobOutcome.NO_MATCH, f"OvertureDB has no {art_type.label} for it"


#: The planned outcome of a saved selection no source ranks above.
KEPT = (JobOutcome.SKIPPED, SAVED_SELECTION)


def visits(plan: AssetPlan) -> dict[int, tuple[Slot, ...]]:
    """Return every planned visit, keyed by owner ID."""
    return {
        owner_id: slots
        for batch in plan.batches()
        for owner_id, slots in batch.visits.items()
    }


def decided(plan: AssetPlan) -> dict[tuple[JobOutcome, str], int]:
    """Return what planning decided for titles, by outcome and reason."""
    return {
        (outcome, reason): count
        for (collection, outcome, reason), count in plan.decided.items()
        if not collection
    }


def _movie(factory: MediaItemFactory, name: str, **overrides: Any) -> MediaItem:
    return factory(
        id=None,
        title=name,
        server_item_id=name,
        library_id="1:lib-1",
        folder_path=f"/media/{name}",
        **overrides,
    )


async def test_overturedb_only_drops_targets_the_catalog_cannot_serve(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    served = _movie(media_item_factory, "Served", tmdb_id=1)
    no_poster = _movie(media_item_factory, "NoPoster", tmdb_id=2)
    absent = _movie(media_item_factory, "Absent", tmdb_id=3)
    db_session.add_all([served, no_poster, absent])
    db_session.add_all(
        [
            catalog_item_factory(
                id=None, tmdb_id=1, poster_url="https://db.test/p.jpg"
            ),
            catalog_item_factory(id=None, tmdb_id=2, poster_url=None),
        ]
    )
    await db_session.commit()

    params = BulkMatchArtRequest(
        art_types=[ArtType.POSTER],
        source_order=[CURRENT_SELECTION, ArtBulkSource.OVERTUREDB],
    )
    plan = await plan_run(params, database=database)

    assert visits(plan) == {row_id(served): ((ArtType.POSTER, None),)}
    assert decided(plan) == {no_art(ArtType.POSTER): 1, NO_ENTRY: 1}
    assert plan.total == 3


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("served", [False, True])
async def test_saved_url_is_skipped_unless_its_file_is_missing(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
    missing: bool,
    served: bool,
) -> None:
    """Only a missing file visits a saved URL; otherwise it is kept."""
    await enable_catalog(db_session)

    item = _movie(
        media_item_factory,
        "Saved",
        tmdb_id=4,
        art={
            "poster": {"url": "https://saved.test/p.jpg"}
            | ({} if missing else RECORDED)
        },
    )
    db_session.add(item)
    if served:
        db_session.add(
            catalog_item_factory(id=None, tmdb_id=4, poster_url="https://db.test/p.jpg")
        )
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[CURRENT_SELECTION, ArtBulkSource.OVERTUREDB],
        ),
        database=database,
    )

    assert len(visits(plan)) == int(missing)
    assert decided(plan) == ({} if missing else {KEPT: 1})


async def test_partial_catalog_entry_drops_only_the_slots_it_lacks(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Media-server URLs saved by sync never hide that the catalog lacks a slot."""
    await enable_catalog(db_session)

    server_art = {
        "poster": {"url": "https://server.test/p.jpg", **RECORDED},
        "background": {"url": "https://server.test/b.jpg", **RECORDED},
    }
    show = _movie(
        media_item_factory,
        "Show",
        media_type=MediaType.SHOW,
        tvdb_id=13,
        art=server_art,
    )
    db_session.add(show)
    public_show = catalog_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        tmdb_id=None,
        tvdb_id=13,
        poster_url="https://db.test/p.jpg",
        background_url=None,
    )
    db_session.add(public_show)
    await db_session.commit()
    seasons = [
        season_factory(id=None, media_item_id=row_id(show), season_num=n, file_count=1)
        for n in (1, 2)
    ]
    db_session.add_all(seasons)
    db_session.add(
        CatalogItemSeason(
            catalog_item_id=row_id(public_show),
            season_num=1,
            poster_url="https://db.test/s1.jpg",
        )
    )
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=list(ArtType),
            source_order=[ArtBulkSource.OVERTUREDB, CURRENT_SELECTION],
        ),
        database=database,
    )
    assert visits(plan) == {
        row_id(show): (
            (ArtType.POSTER, None),
            (ArtType.SEASON_POSTER, row_id(seasons[0])),
        )
    }
    # OvertureDB may replace the server's background but has none: it stays.
    assert decided(plan) == {
        (
            JobOutcome.SKIPPED,
            f"saved selection kept: {no_art(ArtType.BACKGROUND)[1]}",
        ): 1,
        no_art(ArtType.SEASON_POSTER): 1,
    }

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=list(ArtType),
            source_order=[CURRENT_SELECTION, ArtBulkSource.OVERTUREDB],
        ),
        database=database,
    )
    assert visits(plan) == {
        row_id(show): ((ArtType.SEASON_POSTER, row_id(seasons[0])),)
    }
    # Kept first, the server's poster and background stay whatever OvertureDB holds.
    assert decided(plan) == {KEPT: 2, no_art(ArtType.SEASON_POSTER): 1}


async def test_missing_catalog_entry_takes_precedence_over_recent_check(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    db_session.add(
        _movie(media_item_factory, "Recent", tmdb_id=5, last_matched_at=utc_now())
    )
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[CURRENT_SELECTION, ArtBulkSource.OVERTUREDB],
            skip_recent_val=1,
            skip_recent_unit=RecentUnit.DAYS,
        ),
        database=database,
    )

    assert visits(plan) == {}
    assert decided(plan) == {NO_ENTRY: 1}


async def test_a_second_source_keeps_every_target(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Local matching can still find artwork the catalog has never heard of."""
    await enable_catalog(db_session)

    db_session.add(_movie(media_item_factory, "Unknown", tmdb_id=6))
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[
                CURRENT_SELECTION,
                ArtBulkSource.OVERTUREDB,
                ArtBulkSource.LOCAL_ART_MATCHING,
            ],
        ),
        database=database,
    )

    assert len(visits(plan)) == 1
    assert decided(plan) == {}


async def test_season_posters_are_matched_by_season_num(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    show = _movie(media_item_factory, "Show", media_type=MediaType.SHOW, tvdb_id=7)
    db_session.add(show)
    public_show = catalog_item_factory(
        id=None, media_type=MediaType.SHOW, tmdb_id=None, tvdb_id=7, poster_url=None
    )
    db_session.add(public_show)
    await db_session.commit()

    seasons = [
        season_factory(id=None, media_item_id=row_id(show), season_num=n, file_count=3)
        for n in (1, 2)
    ]
    db_session.add_all(seasons)
    db_session.add(
        CatalogItemSeason(
            catalog_item_id=row_id(public_show),
            season_num=2,
            poster_url="https://db.test/s2.jpg",
        )
    )
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.SEASON_POSTER],
            source_order=[CURRENT_SELECTION, ArtBulkSource.OVERTUREDB],
        ),
        database=database,
    )

    assert visits(plan) == {
        row_id(show): ((ArtType.SEASON_POSTER, row_id(seasons[1])),)
    }
    assert decided(plan) == {no_art(ArtType.SEASON_POSTER): 1}


async def test_a_disabled_catalog_drops_every_target(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """With the catalog off there is nothing for its rows to be read from."""
    await disable_catalog(db_session)

    db_session.add(_movie(media_item_factory, "Served", tmdb_id=8))
    db_session.add(
        catalog_item_factory(id=None, tmdb_id=8, poster_url="https://db.test/p.jpg")
    )
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[CURRENT_SELECTION, ArtBulkSource.OVERTUREDB],
        ),
        database=database,
    )

    assert visits(plan) == {}
    assert decided(plan) == {(JobOutcome.SKIPPED, "OvertureDB is disabled"): 1}


async def test_theme_run_drops_items_without_a_catalog_video_id(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    served = _movie(media_item_factory, "Served", tmdb_id=9)
    absent = _movie(media_item_factory, "Absent", tmdb_id=10)
    saved = seed_theme(
        _movie(media_item_factory, "Saved", tmdb_id=11),
        "already-known",
        file_hash="recorded",
    )
    saved_absent = seed_theme(
        _movie(media_item_factory, "SavedAbsent", tmdb_id=14),
        "already-known",
        file_hash="recorded",
    )
    db_session.add_all([served, absent, saved, saved_absent])
    db_session.add_all(
        [
            catalog_item_factory(id=None, tmdb_id=9, youtube_id_overturedb="yt-served"),
            catalog_item_factory(id=None, tmdb_id=11, youtube_id_overturedb="yt-saved"),
            catalog_item_factory(
                id=None, tmdb_id=14, youtube_id_themerrdb="yt-themerrdb"
            ),
        ]
    )
    await db_session.commit()

    params = BulkThemeRequest(
        source_order=[CURRENT_SELECTION, ThemeBulkSource.OVERTUREDB]
    )
    plan = await plan_run(params, database=database)

    assert visits(plan) == {row_id(served): ((ServerAsset.THEME, None),)}
    # The saved themes are kept, whatever OvertureDB holds.
    assert decided(plan) == {KEPT: 2, NO_ENTRY: 1}


async def test_checked_stamper_writes_items_and_seasons_in_one_batch(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    database: Database,
) -> None:

    item = media_item_factory(
        id=None, media_type=MediaType.SHOW, title="Stamped", tmdb_id=12
    )
    db_session.add(item)
    await db_session.commit()
    season = season_factory(id=None, media_item_id=row_id(item), season_num=1)
    db_session.add(season)
    await db_session.commit()

    stamper = CheckedStamper(database=database)
    await stamper.add(item_id=row_id(item), season_id=row_id(season))
    await stamper.add(item_id=row_id(item))

    assert item.last_matched_at is None

    await stamper.flush()
    await db_session.refresh(item)
    await db_session.refresh(season)

    assert item.last_matched_at is not None
    assert season.last_matched_at is not None


async def test_saved_selection_that_is_the_catalog_choice_says_so(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    url = "https://db.test/p.jpg"
    db_session.add(
        _movie(
            media_item_factory,
            "Same",
            tmdb_id=15,
            art={"poster": {"url": url, **RECORDED}},
        )
    )
    db_session.add(catalog_item_factory(id=None, tmdb_id=15, poster_url=url))
    await db_session.commit()

    plan = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB, CURRENT_SELECTION],
        ),
        database=database,
    )

    assert decided(plan) == {
        (
            JobOutcome.SKIPPED,
            "saved selection is already the OvertureDB artwork",
        ): 1
    }


@pytest.mark.parametrize("mode", ["kept", "missing", "replaced"])
async def test_a_disabled_catalog_skips_all_but_saved_restores(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
    mode: str,
) -> None:
    """Nothing is a no match while the catalog is off; restoring needs no catalog.

    *mode* says whether the saved selection is kept (Current selection
    first), missing from disk, or one OvertureDB may replace.
    """
    await disable_catalog(db_session)
    recorded = {} if mode == "missing" else RECORDED
    saved = seed_theme(
        _movie(
            media_item_factory,
            "Saved",
            tmdb_id=16,
            art={"poster": {"url": "https://saved.test/p.jpg", **recorded}},
        ),
        "saved-video",
        file_hash=None if mode == "missing" else "recorded",
    )
    db_session.add_all([saved, _movie(media_item_factory, "Unsaved", tmdb_id=17)])
    db_session.add(
        catalog_item_factory(
            id=None,
            tmdb_id=17,
            poster_url="https://db.test/p.jpg",
            youtube_id_overturedb="yt",
        )
    )
    await db_session.commit()

    def order(source: ArtBulkSource | ThemeBulkSource) -> list[Any]:
        return (
            [source, CURRENT_SELECTION]
            if mode == "replaced"
            else [CURRENT_SELECTION, source]
        )

    art = await plan_run(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER], source_order=order(ArtBulkSource.OVERTUREDB)
        ),
        database=database,
    )
    themes = await plan_run(
        BulkThemeRequest(source_order=order(ThemeBulkSource.OVERTUREDB)),
        database=database,
    )

    restored = mode == "missing"
    assert visits(art) == (
        {row_id(saved): ((ArtType.POSTER, None),)} if restored else {}
    )
    assert visits(themes) == (
        {row_id(saved): ((ServerAsset.THEME, None),)} if restored else {}
    )
    kept = {
        "kept": {(JobOutcome.SKIPPED, SAVED_SELECTION): 1},
        "missing": {},
        "replaced": {(JobOutcome.SKIPPED, f"saved selection kept: {DISABLED[1]}"): 1},
    }[mode]
    assert decided(art) == decided(themes) == {DISABLED: 1, **kept}


@pytest.mark.parametrize("replacing", [False, True], ids=["kept", "replacing"])
async def test_a_theme_in_place_is_kept_when_no_catalog_replaces_it(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    database: Database,
    replacing: bool,
) -> None:
    """A theme nothing selects is held like a saved one, whatever OvertureDB has."""
    await enable_catalog(db_session)
    db_session.add(
        seed_theme(_movie(media_item_factory, "Movie", tmdb_id=19), file_hash="h")
    )
    await db_session.commit()

    plan = await plan_run(
        BulkThemeRequest(
            source_order=[ThemeBulkSource.OVERTUREDB, CURRENT_SELECTION]
            if replacing
            else [CURRENT_SELECTION, ThemeBulkSource.OVERTUREDB]
        ),
        database=database,
    )

    assert visits(plan) == {}
    assert decided(plan) == {
        (
            JobOutcome.SKIPPED,
            f"kept the theme in place: {NO_ENTRY[1]}" if replacing else KEPT_IN_PLACE,
        ): 1
    }


async def test_themerrdb_only_run_names_the_switch_it_needs(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await disable_catalog(db_session)
    db_session.add(_movie(media_item_factory, "Movie", tmdb_id=18))
    await db_session.commit()

    plan = await plan_run(
        BulkThemeRequest(source_order=[CURRENT_SELECTION, ThemeBulkSource.THEMERRDB]),
        database=database,
    )

    assert decided(plan) == {
        (JobOutcome.SKIPPED, "ThemerrDB needs OvertureDB enabled"): 1
    }


async def test_a_theme_that_failed_before_is_planned_as_no_match(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    item = _movie(media_item_factory, "Movie", tmdb_id=19)
    db_session.add(item)
    db_session.add(
        catalog_item_factory(id=None, tmdb_id=19, youtube_id_overturedb="yt-broken")
    )
    await db_session.commit()
    db_session.add(
        DownloadJob(
            media_item_id=row_id(item),
            job_type=JobType.THEME,
            target_url="yt-broken",
            status=JobStatus.FAILED,
            created_at=utc_now(),
        )
    )
    await db_session.commit()

    plan = await plan_run(
        BulkThemeRequest(
            source_order=[
                CURRENT_SELECTION,
                ThemeBulkSource.OVERTUREDB,
                ThemeBulkSource.THEMERRDB,
            ]
        ),
        database=database,
    )

    assert decided(plan) == {
        (
            JobOutcome.NO_MATCH,
            (
                "the OvertureDB theme failed to download before; "
                "ThemerrDB has no theme for it"
            ),
        ): 1
    }


async def test_a_theme_that_succeeded_after_failing_is_planned_again(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    catalog_item_factory: CatalogItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_catalog(db_session)

    item = _movie(media_item_factory, "Movie", tmdb_id=19)
    db_session.add(item)
    db_session.add(
        catalog_item_factory(id=None, tmdb_id=19, youtube_id_overturedb="yt-flaky")
    )
    await db_session.commit()
    failed_at = utc_now()
    for status, created_at in (
        (JobStatus.FAILED, failed_at),
        (JobStatus.DONE, failed_at + timedelta(minutes=1)),
    ):
        db_session.add(
            DownloadJob(
                media_item_id=row_id(item),
                job_type=JobType.THEME,
                target_url="yt-flaky",
                status=status,
                created_at=created_at,
            )
        )
    await db_session.commit()

    plan = await plan_run(
        BulkThemeRequest(source_order=[CURRENT_SELECTION, ThemeBulkSource.OVERTUREDB]),
        database=database,
    )

    assert decided(plan) == {}
