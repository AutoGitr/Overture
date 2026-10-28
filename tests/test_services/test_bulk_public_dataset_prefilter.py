"""Coverage for planning out bulk targets OvertureDB cannot serve."""

lazy from typing import Any

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetSeason
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtBulkSource,
    ArtType,
    JobStatus,
    JobType,
    MediaType,
    RecentUnit,
    ThemeBulkSource,
)
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.services import bulk_common
lazy from overture.services.art import bulk_work
lazy from overture.services.bulk_common import AssetPlan
lazy from overture.services.themes import bulk as theme_bulk
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.factories import (
    MediaItemFactory,
    PublicDatasetItemFactory,
    SeasonFactory,
)
lazy from tests.runtime_helpers import make_local_assets, row_id

NO_ENTRY = (JobOutcome.NO_MATCH, "OvertureDB has no entry for it")
DISABLED = (JobOutcome.SKIPPED, "OvertureDB is disabled")
#: The stored facts of a slot's file on disk.
RECORDED = {"file_hash": "recorded", "file_mtime_ns": 1, "file_size": 1}


def no_art(art_type: ArtType) -> tuple[JobOutcome, str]:
    """Return the planned outcome of a slot an OvertureDB entry lacks."""
    return JobOutcome.NO_MATCH, f"OvertureDB has no {art_type.label} for it"


def differs(label: str) -> tuple[JobOutcome, str]:
    """Return the planned outcome of a saved selection the catalog differs from."""
    return (
        JobOutcome.SKIPPED,
        (
            f"saved selection differs from the {label}; Replace existing would "
            "replace it"
        ),
    )


def visits[TargetT](plan: AssetPlan[TargetT]) -> dict[int, tuple[TargetT, ...]]:
    """Return every planned visit, keyed by item ID."""
    return {
        item_id: targets
        for batch in plan.batches()
        for item_id, targets in batch.items()
    }


def _movie(factory: MediaItemFactory, name: str, **overrides: Any) -> MediaItem:
    return factory(
        id=None,
        title=name,
        server_item_id=name,
        library_id="lib-1",
        folder_path=f"/media/{name}",
        **overrides,
    )


async def test_overturedb_only_drops_targets_the_dataset_cannot_serve(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_public_dataset(db_session)

    served = _movie(media_item_factory, "Served", tmdb_id=1)
    no_poster = _movie(media_item_factory, "NoPoster", tmdb_id=2)
    absent = _movie(media_item_factory, "Absent", tmdb_id=3)
    db_session.add_all([served, no_poster, absent])
    db_session.add_all(
        [
            public_dataset_item_factory(
                id=None, tmdb_id=1, poster_url="https://db.test/p.jpg"
            ),
            public_dataset_item_factory(id=None, tmdb_id=2, poster_url=None),
        ]
    )
    await db_session.commit()

    params = BulkMatchArtRequest(
        art_types=[ArtType.POSTER], source_order=[ArtBulkSource.OVERTUREDB]
    )
    plan = await bulk_work.plan_bulk_art(
        params, app_config=app_config, database=database
    )

    assert visits(plan) == {row_id(served): ((ArtType.POSTER, None),)}
    assert plan.decided == {no_art(ArtType.POSTER): 1, NO_ENTRY: 1}
    assert plan.total == 3
    work = await bulk_work.load_art_batch(
        params,
        visits(plan),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )
    assert [item.title for item, _art_type, _season in work.targets] == ["Served"]
    assert work.public_index.art_url(served, ArtType.POSTER) == "https://db.test/p.jpg"


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("served", [False, True])
async def test_saved_url_is_skipped_unless_its_file_is_missing(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
    missing: bool,
    served: bool,
) -> None:
    """Only a missing file visits a saved URL; one the dataset lacks is no match."""
    await enable_public_dataset(db_session)

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
            public_dataset_item_factory(
                id=None, tmdb_id=4, poster_url="https://db.test/p.jpg"
            )
        )
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB],
        ),
        app_config=app_config,
        database=database,
    )

    assert len(visits(plan)) == int(missing)
    skipped = differs("OvertureDB artwork") if served else NO_ENTRY
    assert plan.decided == ({} if missing else {skipped: 1})


async def test_partial_dataset_entry_drops_only_the_slots_it_lacks(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Media-server URLs saved by sync never hide that the dataset lacks a slot."""
    await enable_public_dataset(db_session)

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
    public_show = public_dataset_item_factory(
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
        PublicDatasetSeason(
            public_dataset_item_id=row_id(public_show),
            season_num=1,
            poster_url="https://db.test/s1.jpg",
        )
    )
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=list(ArtType),
            source_order=[ArtBulkSource.OVERTUREDB],
            overwrite_existing=True,
        ),
        app_config=app_config,
        database=database,
    )
    assert visits(plan) == {
        row_id(show): (
            (ArtType.POSTER, None),
            (ArtType.SEASON_POSTER, row_id(seasons[0])),
        )
    }
    assert plan.decided == {
        no_art(ArtType.BACKGROUND): 1,
        no_art(ArtType.SEASON_POSTER): 1,
    }

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=list(ArtType), source_order=[ArtBulkSource.OVERTUREDB]
        ),
        app_config=app_config,
        database=database,
    )
    assert visits(plan) == {
        row_id(show): ((ArtType.SEASON_POSTER, row_id(seasons[0])),)
    }
    assert plan.decided == {
        differs("OvertureDB artwork"): 1,
        no_art(ArtType.BACKGROUND): 1,
        no_art(ArtType.SEASON_POSTER): 1,
    }


async def test_missing_dataset_entry_takes_precedence_over_recent_check(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_public_dataset(db_session)

    db_session.add(
        _movie(media_item_factory, "Recent", tmdb_id=5, last_matched_at=utc_now())
    )
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB],
            skip_recent_val=1,
            skip_recent_unit=RecentUnit.DAYS,
        ),
        app_config=app_config,
        database=database,
    )

    assert visits(plan) == {}
    assert plan.decided == {NO_ENTRY: 1}


async def test_a_second_source_keeps_every_target(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Local matching can still find artwork the dataset has never heard of."""
    await enable_public_dataset(db_session)

    db_session.add(_movie(media_item_factory, "Unknown", tmdb_id=6))
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB, ArtBulkSource.LOCAL_ART_MATCHING],
        ),
        app_config=app_config,
        database=database,
    )

    assert len(visits(plan)) == 1
    assert plan.decided == {}


async def test_season_posters_are_matched_by_season_num(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_public_dataset(db_session)

    show = _movie(media_item_factory, "Show", media_type=MediaType.SHOW, tvdb_id=7)
    db_session.add(show)
    public_show = public_dataset_item_factory(
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
        PublicDatasetSeason(
            public_dataset_item_id=row_id(public_show),
            season_num=2,
            poster_url="https://db.test/s2.jpg",
        )
    )
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.SEASON_POSTER], source_order=[ArtBulkSource.OVERTUREDB]
        ),
        app_config=app_config,
        database=database,
    )

    assert visits(plan) == {
        row_id(show): ((ArtType.SEASON_POSTER, row_id(seasons[1])),)
    }
    assert plan.decided == {no_art(ArtType.SEASON_POSTER): 1}


async def test_a_disabled_dataset_drops_every_target(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """With the dataset off there is nothing for its rows to be read from."""

    db_session.add(_movie(media_item_factory, "Served", tmdb_id=8))
    db_session.add(
        public_dataset_item_factory(
            id=None, tmdb_id=8, poster_url="https://db.test/p.jpg"
        )
    )
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER], source_order=[ArtBulkSource.OVERTUREDB]
        ),
        app_config=app_config,
        database=database,
    )

    assert visits(plan) == {}
    assert plan.decided == {(JobOutcome.SKIPPED, "OvertureDB is disabled"): 1}


async def test_theme_run_drops_items_without_a_dataset_video_id(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_public_dataset(db_session)

    served = _movie(media_item_factory, "Served", tmdb_id=9)
    absent = _movie(media_item_factory, "Absent", tmdb_id=10)
    saved = _movie(
        media_item_factory,
        "Saved",
        tmdb_id=11,
        youtube_id="already-known",
        theme_file_hash="recorded",
    )
    saved_absent = _movie(
        media_item_factory,
        "SavedAbsent",
        tmdb_id=14,
        youtube_id="already-known",
        theme_file_hash="recorded",
    )
    db_session.add_all([served, absent, saved, saved_absent])
    db_session.add_all(
        [
            public_dataset_item_factory(
                id=None, tmdb_id=9, youtube_id_overturedb="yt-served"
            ),
            public_dataset_item_factory(
                id=None, tmdb_id=11, youtube_id_overturedb="yt-saved"
            ),
            public_dataset_item_factory(
                id=None, tmdb_id=14, youtube_id_themerrdb="yt-themerrdb"
            ),
        ]
    )
    await db_session.commit()

    params = BulkThemeRequest(source_order=[ThemeBulkSource.OVERTUREDB])
    plan = await theme_bulk.plan_bulk_themes(
        params, app_config=app_config, database=database
    )

    assert visits(plan) == {row_id(served): (None,)}
    assert plan.decided == {
        differs("OvertureDB theme"): 1,
        NO_ENTRY: 1,
        (JobOutcome.NO_MATCH, "OvertureDB has no theme for it"): 1,
    }
    work = await theme_bulk.load_theme_batch(
        params,
        list(visits(plan)),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )
    assert [item.title for item in work.items] == ["Served"]
    assert (
        work.public_index.theme(served, [ThemeBulkSource.OVERTUREDB]).value
        == "yt-served"
    )


async def test_checked_stamper_writes_items_and_seasons_in_one_batch(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    database: Database,
) -> None:

    item = _movie(media_item_factory, "Stamped", tmdb_id=12)
    db_session.add(item)
    await db_session.commit()
    season = season_factory(id=None, media_item_id=row_id(item), season_num=1)
    db_session.add(season)
    await db_session.commit()

    stamper = bulk_common.CheckedStamper(database=database)
    await stamper.add(row_id(item), season_id=row_id(season))
    await stamper.add(row_id(item))

    assert item.last_matched_at is None

    await stamper.flush()
    await db_session.refresh(item)
    await db_session.refresh(season)

    assert item.last_matched_at is not None
    assert season.last_matched_at is not None


async def test_saved_selection_that_is_the_catalog_choice_says_so(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_public_dataset(db_session)

    url = "https://db.test/p.jpg"
    db_session.add(
        _movie(
            media_item_factory,
            "Same",
            tmdb_id=15,
            art={"poster": {"url": url, **RECORDED}},
        )
    )
    db_session.add(public_dataset_item_factory(id=None, tmdb_id=15, poster_url=url))
    await db_session.commit()

    plan = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER], source_order=[ArtBulkSource.OVERTUREDB]
        ),
        app_config=app_config,
        database=database,
    )

    assert plan.decided == {
        (
            JobOutcome.SKIPPED,
            "saved selection is already the OvertureDB artwork",
        ): 1
    }


@pytest.mark.parametrize("mode", ["default", "missing", "overwrite"])
async def test_a_disabled_dataset_skips_all_but_saved_restores(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
    mode: str,
) -> None:
    """Nothing is a no match while the catalog is off; restoring needs no catalog."""
    recorded = {} if mode == "missing" else RECORDED
    saved = _movie(
        media_item_factory,
        "Saved",
        tmdb_id=16,
        youtube_id="saved-video",
        theme_file_hash=recorded.get("file_hash"),
        art={"poster": {"url": "https://saved.test/p.jpg", **recorded}},
    )
    db_session.add_all([saved, _movie(media_item_factory, "Unsaved", tmdb_id=17)])
    db_session.add(
        public_dataset_item_factory(
            id=None,
            tmdb_id=17,
            poster_url="https://db.test/p.jpg",
            youtube_id_overturedb="yt",
        )
    )
    await db_session.commit()
    options: dict[str, Any] = {"overwrite_existing": mode == "overwrite"}

    art = await bulk_work.plan_bulk_art(
        BulkMatchArtRequest(
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB],
            **options,
        ),
        app_config=app_config,
        database=database,
    )
    themes = await theme_bulk.plan_bulk_themes(
        BulkThemeRequest(source_order=[ThemeBulkSource.OVERTUREDB], **options),
        app_config=app_config,
        database=database,
    )

    restored = mode == "missing"
    assert visits(art) == (
        {row_id(saved): ((ArtType.POSTER, None),)} if restored else {}
    )
    assert visits(themes) == ({row_id(saved): (None,)} if restored else {})
    assert art.decided == themes.decided == {DISABLED: 1 if restored else 2}


async def test_themerrdb_only_run_names_the_switch_it_needs(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    db_session.add(_movie(media_item_factory, "Movie", tmdb_id=18))
    await db_session.commit()

    plan = await theme_bulk.plan_bulk_themes(
        BulkThemeRequest(source_order=[ThemeBulkSource.THEMERRDB]),
        app_config=app_config,
        database=database,
    )

    assert plan.decided == {
        (JobOutcome.SKIPPED, "ThemerrDB needs OvertureDB enabled"): 1
    }


async def test_a_theme_that_failed_before_is_planned_as_no_match(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    public_dataset_item_factory: PublicDatasetItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await enable_public_dataset(db_session)

    item = _movie(media_item_factory, "Movie", tmdb_id=19)
    db_session.add(item)
    db_session.add(
        public_dataset_item_factory(
            id=None, tmdb_id=19, youtube_id_overturedb="yt-broken"
        )
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

    plan = await theme_bulk.plan_bulk_themes(
        BulkThemeRequest(
            source_order=[ThemeBulkSource.OVERTUREDB, ThemeBulkSource.THEMERRDB]
        ),
        app_config=app_config,
        database=database,
    )

    assert plan.decided == {
        (
            JobOutcome.NO_MATCH,
            (
                "the OvertureDB theme failed to download before; "
                "ThemerrDB has no theme for it"
            ),
        ): 1
    }
