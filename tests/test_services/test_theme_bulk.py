"""Source decisions and outcomes in services.themes.bulk."""

lazy import asyncio
lazy from pathlib import Path
lazy from typing import Any, Literal, cast

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    CURRENT_SELECTION,
    MediaType,
    RecentUnit,
    ThemeBulkSource,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.results import latest_runs
lazy from overture.schemas.bulk import (
    BulkThemeRequest,
)
lazy from overture.schemas.themes import ThemeSearchResult
lazy from overture.services.asset_runs import run as asset_run
lazy from overture.services.asset_runs.plan import KEPT_IN_PLACE, SAVED_SELECTION
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.time import utc_now
lazy from overture.ws.events import validate_event_payload
lazy from tests.bulk_helpers import (
    BulkThemeWork,
    Context,
    as_job_context,
    bind_stamper,
    enable_catalog,
    make_bulk_downloads,
    movie_item,
    planned_event,
    progress_logs,
    public_index,
    use_theme_work,
)
lazy from tests.factories import seed_theme
lazy from tests.media_servers import served_item
lazy from tests.runtime_helpers import (
    make_local_assets,
    unused,
)


@pytest.mark.parametrize("fallback", [False, True])
async def test_source_failure_is_reported_even_when_a_later_source_matches(
    fallback: bool,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    index = public_index(
        1,
        youtube_id_overturedb="public-video" if fallback else None,
        poster_url="https://public.test/poster.jpg" if fallback else None,
    )

    async def fail(*_args: Any, **_kwargs: Any):
        raise ValueError("source unavailable")

    async def queue(*_args: Any, **_kwargs: Any) -> bool:
        return True

    context = Context()
    downloads = make_bulk_downloads(app_config=app_config, database=database)

    class FailedSearch:
        async def search(self, query: str, limit: int = 10):
            return await fail()

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title}", index))
    monkeypatch.setattr(asset_run, "queue_download", queue)
    stamper = bind_stamper(monkeypatch)
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[
                CURRENT_SELECTION,
                ThemeBulkSource.YOUTUBE_SEARCH,
                ThemeBulkSource.OVERTUREDB,
            ]
        ),
        downloads=downloads,
        youtube_resolver=cast("Any", FailedSearch()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    logs = [str(line) for line in progress_logs(context)]
    target = "Movie (theme)"
    failed = "YouTube search: source unavailable"
    if fallback:
        # The failure is its own error line; the later source still decides.
        assert logs[0] == f"Error {target} - {failed}"
        assert logs[1].startswith(f"Queued {target} - OvertureDB ")
        assert len(logs) == 2
    else:
        assert len(logs) == 1
        assert logs[0].startswith(f"Error {target} - {failed}")
        assert "OvertureDB has no" in logs[0]
    assert stamper.checked == ([1] if fallback else [])
    result = context.events[-1][1]
    assert result["log_targets"].get("Error", 0) == result["done"] == 1
    assert result["log_targets"].get("Queued", 0) == int(fallback)
    assert result["log_targets"].get("Downloaded", 0) == 0


async def test_bulk_theme_source_order_falls_back_to_youtube_search(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = seed_theme(
        served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            year=1979,
            last_matched_at=None,
        ),
        None,
    )
    queued: list[str] = []

    async def fake_search(_query: str, *, limit: int) -> list[ThemeSearchResult]:
        assert limit == 1
        return [ThemeSearchResult(id="abcDEF12345", title="Movie Theme")]

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(f"{target.media_item_id}:{target.target_url}")
        return True

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme"))
    monkeypatch.setattr(asset_run, "queue_download", fake_queue)
    stamper = bind_stamper(monkeypatch)

    class FakeYoutubeResolver:
        async def search(self, query: str, limit: int = 10) -> list[ThemeSearchResult]:
            return await fake_search(query, limit=limit)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[
                CURRENT_SELECTION,
                ThemeBulkSource.OVERTUREDB,
                ThemeBulkSource.YOUTUBE_SEARCH,
            ]
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=cast("Any", FakeYoutubeResolver()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert queued == ["1:abcDEF12345"]
    assert stamper.checked == [1]
    assert progress_logs(context) == [
        "Queued Movie (theme) - YouTube search: Movie Theme"
    ]
    completed = context.events[-1][1]
    assert completed["log_targets"].get("Queued", 0) == 1


async def test_bulk_theme_existing_youtube_id_without_file_queues_download(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = seed_theme(
        served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            year=1979,
            folder_path="/media/Movie",
            last_matched_at=None,
        ),
        "abcDEF12345",
    )
    queued: list[str] = []

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(f"{target.media_item_id}:{target.target_url}")
        return True

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme"))
    monkeypatch.setattr(asset_run, "queue_download", fake_queue)
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert queued == ["1:abcDEF12345"]
    log = progress_logs(context)[-1]
    assert isinstance(log, str)
    assert (
        log == "Queued Movie (theme) - restores the saved selection; local file missing"
    )


async def test_bulk_theme_queue_failure_does_not_abort_remaining_items(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    failing = seed_theme(
        served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Broken",
            folder_path=str(tmp_path / "Broken"),
        ),
        "abcDEF12345",
    )
    complete = seed_theme(
        served_item(
            id=2,
            media_type=MediaType.MOVIE,
            title="Complete",
        ),
        file_hash="theme-hash",
    )

    complete.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    async def fail_queue(*_args: object, **_kwargs: object) -> bool:
        raise OSError("storage unavailable")

    use_theme_work(monkeypatch, BulkThemeWork([failing, complete], "{title} theme"))
    monkeypatch.setattr(asset_run, "queue_download", fail_queue)
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert len(progress_logs(context)) == 2
    completed = context.events[-1][1]
    assert completed["done"] == 2
    assert completed["log_targets"].get("Error", 0) == 1
    assert completed["log_targets"].get("Skipped", 0) == 1


async def test_bulk_theme_skip_recent_suppresses_source_lookup(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """A recently checked item is decided while planning: nothing is read."""

    async def unexpected(*_args: object, **_kwargs: object):
        raise AssertionError("recently checked items are never read or searched")

    db_session.add_all(
        served_item(
            id=n,
            media_type=MediaType.MOVIE,
            title=f"Movie {n}",
            folder_path=f"/media/Movie {n}",
            last_matched_at=utc_now(),
        )
        for n in (1, 2)
    )
    await db_session.commit()
    local_assets = make_local_assets(app_config=app_config, database=database)
    monkeypatch.setattr(local_assets, "reconcile", unexpected)
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(skip_recent_val=1, skip_recent_unit=RecentUnit.DAYS),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=local_assets,
        database=database,
    )

    assert progress_logs(context) == [
        "Skipped 2 assets - checked within the last 1 day"
    ]
    completed = context.events[-1][1]
    assert completed["log_targets"].get("Skipped", 0) == completed["total"] == 2


@pytest.mark.parametrize("source", ["overturedb", "themerrdb"])
async def test_bulk_theme_items_without_catalog_theme_are_counted_in_one_step(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
    source: Literal["overturedb", "themerrdb"],
) -> None:
    """Items no catalog serves are decided while planning, in one line."""

    async def unexpected(*_args: object, **_kwargs: object):
        raise AssertionError("planned items are never read")

    db_session.add_all(
        served_item(
            id=n,
            title=f"Movie {n}",
            media_type=MediaType.MOVIE,
            folder_path=f"/media/Movie {n}",
        )
        for n in range(1, 151)
    )
    await enable_catalog(db_session)
    local_assets = make_local_assets(app_config=app_config, database=database)
    monkeypatch.setattr(local_assets, "reconcile", unexpected)
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[CURRENT_SELECTION, ThemeBulkSource(source)]),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=local_assets,
        database=database,
    )

    reason = (
        "OvertureDB has no entry for it"
        if source == "overturedb"
        else "ThemerrDB has no theme for it"
    )
    assert progress_logs(context) == [f"No match 150 assets - {reason}"]
    assert planned_event(context)["total"] == 150
    completed = context.events[-1][1]
    assert completed["total"] == completed["log_targets"].get("No match", 0) == 150


async def test_bulk_theme_says_why_an_item_with_a_theme_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = seed_theme(
        served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
        ),
        file_hash="theme-hash",
    )

    item.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [f"Skipped Movie (theme) - {KEPT_IN_PLACE}"]


async def test_bulk_theme_says_item_with_saved_youtube_id_was_already_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = seed_theme(
        served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
        ),
        "abcDEF12345",
        file_hash="theme-hash",
    )

    item.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [f"Skipped Movie (theme) - {SAVED_SELECTION}"]


async def test_bulk_theme_says_item_with_saved_youtube_title_was_already_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = seed_theme(
        served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
        ),
        title="Movie Theme",
        file_hash="theme-hash",
    )

    item.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [f"Skipped Movie (theme) - {KEPT_IN_PLACE}"]


async def test_bulk_theme_single_item_without_catalog_theme_has_singular_plurality(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    db_session.add(
        served_item(
            id=1, title="Movie", media_type=MediaType.MOVIE, folder_path="/media/Movie"
        )
    )
    await enable_catalog(db_session)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[CURRENT_SELECTION, ThemeBulkSource.OVERTUREDB]),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [
        "No match 1 asset - OvertureDB has no entry for it"
    ]


@pytest.mark.parametrize(
    ("source_order", "expected"),
    [
        (["overturedb"], "No match Movie (theme) - OvertureDB has no entry for it"),
        (["themerrdb"], "No match Movie (theme) - ThemerrDB has no theme for it"),
        (
            ["youtube_search"],
            "No match Movie (theme) - YouTube search: no result for 'Movie theme'",
        ),
        (
            ["overturedb", "themerrdb"],
            (
                "No match Movie (theme) - OvertureDB has no entry for it; "
                "ThemerrDB has no theme for it"
            ),
        ),
        (
            ["overturedb", "youtube_search"],
            (
                "No match Movie (theme) - OvertureDB has no entry for it; "
                "YouTube search: no result for 'Movie theme'"
            ),
        ),
        (
            ["youtube_search", "overturedb"],
            (
                "No match Movie (theme) - YouTube search: no result for 'Movie theme'; "
                "OvertureDB has no entry for it"
            ),
        ),
        (
            ["overturedb", "themerrdb", "youtube_search"],
            (
                "No match Movie (theme) - OvertureDB has no entry for it; "
                "ThemerrDB has no theme for it; "
                "YouTube search: no result for 'Movie theme'"
            ),
        ),
    ],
)
async def test_bulk_theme_names_the_sources_that_found_nothing(
    monkeypatch: pytest.MonkeyPatch,
    source_order: list[str],
    expected: str,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie")

    class EmptyResolver:
        async def search(self, query: str, limit: int = 10) -> list[ThemeSearchResult]:
            _ = (query, limit)
            return []

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[CURRENT_SELECTION, *map(ThemeBulkSource, source_order)]
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=cast("Any", EmptyResolver()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [expected]


async def test_bulk_theme_selects_overturedb_or_themerrdb_by_configured_order(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    index = public_index(
        1,
        youtube_id_overturedb="yt-overture",
        youtube_id_themerrdb="yt-themerr",
    )
    queued: list[str | None] = []

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target.target_url)
        return True

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title} theme", index))
    monkeypatch.setattr(asset_run, "queue_download", fake_queue)
    bind_stamper(monkeypatch)

    # Order 1: overturedb first
    context1 = Context()
    await asset_run.run_themes(
        as_job_context(context1),
        BulkThemeRequest(
            source_order=[
                CURRENT_SELECTION,
                ThemeBulkSource.OVERTUREDB,
                ThemeBulkSource.THEMERRDB,
            ]
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    assert queued == ["yt-overture"]
    assert any(
        "Queued Movie (theme) - OvertureDB theme" in str(line)
        for line in progress_logs(context1)
    )

    # Order 2: themerrdb first
    queued.clear()
    context2 = Context()
    await asset_run.run_themes(
        as_job_context(context2),
        BulkThemeRequest(
            source_order=[
                CURRENT_SELECTION,
                ThemeBulkSource.THEMERRDB,
                ThemeBulkSource.OVERTUREDB,
            ]
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    assert queued == ["yt-themerr"]
    assert any(
        "Queued Movie (theme) - ThemerrDB theme" in str(line)
        for line in progress_logs(context2)
    )


async def test_bulk_theme_tries_a_theme_that_failed_to_download_before_again(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    index = public_index(
        1,
        youtube_id_overturedb="yt-overture-failed",
        youtube_id_themerrdb="yt-themerr-working",
    )
    queued: list[str | None] = []

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target.target_url)
        return True

    use_theme_work(
        monkeypatch,
        BulkThemeWork([item], "{title} theme", index),
    )
    monkeypatch.setattr(asset_run, "queue_download", fake_queue)
    bind_stamper(monkeypatch)

    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[
                CURRENT_SELECTION,
                ThemeBulkSource.OVERTUREDB,
                ThemeBulkSource.THEMERRDB,
            ]
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    # The first source's theme failed once; YouTube may serve it now.
    assert queued == ["yt-overture-failed"]
    assert any(
        "Queued Movie (theme) - OvertureDB theme" in str(line)
        for line in progress_logs(context)
    )


async def test_theme_searches_overlap_but_items_are_reported_in_plan_order(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    items = [movie_item(id=index, title=f"Movie {index}") for index in range(1, 6)]
    running = 0
    peak = 0

    class SlowSearch:
        async def search(self, query: str, limit: int = 10) -> list[ThemeSearchResult]:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            # Earlier items take more event-loop turns, so they finish last.
            for _ in range(6 - int(query.rsplit(" ", 1)[1])):
                await asyncio.sleep(0)
            running -= 1
            return [ThemeSearchResult(id=f"video-{query}", title=query)]

    async def queue(*_args: Any, **_kwargs: Any) -> bool:
        return True

    context = Context()
    use_theme_work(monkeypatch, BulkThemeWork(items, "{title}"))
    monkeypatch.setattr(asset_run, "queue_download", queue)
    bind_stamper(monkeypatch)

    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[CURRENT_SELECTION, ThemeBulkSource.YOUTUBE_SEARCH]
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=cast("Any", SlowSearch()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    queued = [line for line in progress_logs(context) if line.startswith("Queued")]
    assert [line.split(" - ")[0] for line in queued] == [
        f"Queued Movie {index} (theme)" for index in range(1, 6)
    ]
    assert peak > 1


async def test_bulk_themes_persists_job_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    context = Context(JobKind.BULK_THEME)
    downloads = make_bulk_downloads(app_config=app_config, database=database)

    use_theme_work(monkeypatch, BulkThemeWork([item], "{title}"))
    bind_stamper(monkeypatch)

    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[CURRENT_SELECTION, ThemeBulkSource.OVERTUREDB]),
        downloads=downloads,
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    runs = await latest_runs(database)
    assert JobKind.BULK_THEME in runs
    run = runs[JobKind.BULK_THEME]
    assert run.finished_at is not None
    assert run.event == "theme.completed"
    assert validate_event_payload(run.event, run.summary) is not None
