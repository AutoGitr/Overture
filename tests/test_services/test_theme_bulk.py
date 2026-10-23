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
    MediaType,
    RecentUnit,
    ThemeBulkSource,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.schemas.bulk import (
    BulkThemeRequest,
)
lazy from overture.schemas.themes import ThemeSearchResult
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.job_results import latest_runs
lazy from overture.services.themes import bulk as theme_bulk
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.time import utc_now
lazy from overture.ws.events import validate_event_payload
lazy from tests.bulk_helpers import (
    Context,
    as_job_context,
    bind_stamper,
    enable_public_dataset,
    make_bulk_downloads,
    movie_item,
    progress_logs,
    public_index,
    use_theme_work,
)
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

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title}", index))
    monkeypatch.setattr(theme_bulk, "queue_download", queue)
    stamper = bind_stamper(monkeypatch, theme_bulk)
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[
                ThemeBulkSource.YOUTUBE_SEARCH,
                ThemeBulkSource.OVERTUREDB,
            ]
        ),
        downloads,
        cast("Any", FailedSearch()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    logs = [str(line) for line in progress_logs(context)]
    target = "Movie"
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
    assert result["errors"] == result["done"] == 1
    assert result["queued"] == int(fallback)
    assert result["downloaded"] == 0


async def test_bulk_theme_source_order_falls_back_to_youtube_search(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        year=1979,
        youtube_id=None,
        last_matched_at=None,
    )
    queued: list[str] = []

    async def fake_search(_query: str, *, limit: int) -> list[ThemeSearchResult]:
        assert limit == 1
        return [ThemeSearchResult(id="abcDEF12345", title="Movie Theme")]

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(f"{target.media_item_id}:{target.target_url}")
        return True

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme"))
    monkeypatch.setattr(theme_bulk, "queue_download", fake_queue)
    stamper = bind_stamper(monkeypatch, theme_bulk)

    class FakeYoutubeResolver:
        async def search(self, query: str, limit: int = 10) -> list[ThemeSearchResult]:
            return await fake_search(query, limit=limit)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[ThemeBulkSource.OVERTUREDB, ThemeBulkSource.YOUTUBE_SEARCH]
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        cast("Any", FakeYoutubeResolver()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert queued == ["1:abcDEF12345"]
    assert stamper.checked == [1]
    assert progress_logs(context) == ["Queued Movie - YouTube search: Movie Theme"]
    completed = context.events[-1][1]
    assert completed["queued"] == 1


async def test_bulk_theme_existing_youtube_id_without_file_queues_download(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        year=1979,
        youtube_id="abcDEF12345",
        last_matched_at=None,
    )
    queued: list[str] = []

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(f"{target.media_item_id}:{target.target_url}")
        return True

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme"))
    monkeypatch.setattr(theme_bulk, "queue_download", fake_queue)
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(retry_saved_downloads=True),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert queued == ["1:abcDEF12345"]
    log = progress_logs(context)[-1]
    assert isinstance(log, str)
    assert (
        log == "Queued Movie - restores the saved selection; local theme file missing"
    )


async def test_bulk_theme_queue_failure_does_not_abort_remaining_items(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    failing = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Broken",
        youtube_id="abcDEF12345",
    )
    complete = MediaItem(
        id=2,
        media_type=MediaType.MOVIE,
        title="Complete",
        theme_file_hash="theme-hash",
    )

    complete.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    async def fail_queue(*_args: object, **_kwargs: object) -> bool:
        raise OSError("storage unavailable")

    use_theme_work(
        monkeypatch, theme_bulk.BulkThemeWork([failing, complete], "{title} theme")
    )
    monkeypatch.setattr(theme_bulk, "queue_download", fail_queue)
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(retry_saved_downloads=True),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert len(progress_logs(context)) == 2
    completed = context.events[-1][1]
    assert completed["done"] == 2
    assert completed["errors"] == 1
    assert completed["skipped"] == 1


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
        MediaItem(
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
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(skip_recent_val=1, skip_recent_unit=RecentUnit.DAYS),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=local_assets,
        database=database,
    )

    assert progress_logs(context) == ["Skipped 2 items - checked within the last 1 day"]
    completed = context.events[-1][1]
    assert completed["skipped"] == completed["total"] == 2


@pytest.mark.parametrize("source", ["overturedb", "themerrdb"])
async def test_bulk_theme_items_without_dataset_theme_are_counted_in_one_step(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
    source: Literal["overturedb", "themerrdb"],
) -> None:
    """Items no dataset serves are decided while planning, in one line."""

    async def unexpected(*_args: object, **_kwargs: object):
        raise AssertionError("planned items are never read")

    db_session.add_all(
        MediaItem(
            id=n,
            title=f"Movie {n}",
            media_type=MediaType.MOVIE,
            folder_path=f"/media/Movie {n}",
        )
        for n in range(1, 151)
    )
    await enable_public_dataset(db_session)
    local_assets = make_local_assets(app_config=app_config, database=database)
    monkeypatch.setattr(local_assets, "reconcile", unexpected)
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[ThemeBulkSource(source)]),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=local_assets,
        database=database,
    )

    reason = (
        "OvertureDB has no entry for it"
        if source == "overturedb"
        else "ThemerrDB has no theme for it"
    )
    assert progress_logs(context) == [f"No match 150 items - {reason}"]
    assert context.events[1][1]["total"] == 150
    completed = context.events[-1][1]
    assert completed["total"] == completed["no_match"] == 150


async def test_bulk_theme_says_why_an_item_with_a_theme_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        theme_file_hash="theme-hash",
    )

    item.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [
        (
            "Skipped Movie - kept the local theme file "
            "(Overwrite existing would replace it)"
        )
    ]


async def test_bulk_theme_says_item_with_saved_youtube_id_was_already_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        youtube_id="abcDEF12345",
        theme_file_hash="theme-hash",
    )

    item.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(retry_saved_downloads=True),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [
        "Skipped Movie - saved selection kept; its local theme file is present"
    ]


async def test_bulk_theme_says_item_with_saved_youtube_title_was_already_downloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        youtube_title="Movie Theme",
        theme_file_hash="theme-hash",
    )

    item.folder_path = str(tmp_path)
    (tmp_path / "theme.mp3").write_bytes(b"existing asset")

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [
        (
            "Skipped Movie - kept the local theme file "
            "(Overwrite existing would replace it)"
        )
    ]


async def test_bulk_theme_single_item_without_dataset_theme_has_singular_plurality(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    db_session.add(
        MediaItem(
            id=1, title="Movie", media_type=MediaType.MOVIE, folder_path="/media/Movie"
        )
    )
    await enable_public_dataset(db_session)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[ThemeBulkSource.OVERTUREDB]),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert progress_logs(context) == [
        "No match 1 item - OvertureDB has no entry for it"
    ]


@pytest.mark.parametrize(
    ("source_order", "expected"),
    [
        (["overturedb"], "No match Movie - OvertureDB has no entry for it"),
        (["themerrdb"], "No match Movie - ThemerrDB has no theme for it"),
        (
            ["youtube_search"],
            "No match Movie - YouTube search: no result for 'Movie theme'",
        ),
        (
            ["overturedb", "themerrdb"],
            (
                "No match Movie - OvertureDB has no entry for it; "
                "ThemerrDB has no theme for it"
            ),
        ),
        (
            ["overturedb", "youtube_search"],
            (
                "No match Movie - OvertureDB has no entry for it; "
                "YouTube search: no result for 'Movie theme'"
            ),
        ),
        (
            ["youtube_search", "overturedb"],
            (
                "No match Movie - YouTube search: no result for 'Movie theme'; "
                "OvertureDB has no entry for it"
            ),
        ),
        (
            ["overturedb", "themerrdb", "youtube_search"],
            (
                "No match Movie - OvertureDB has no entry for it; ThemerrDB has "
                "no theme for it; YouTube search: no result for 'Movie theme'"
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

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme"))
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=cast("list[Any]", source_order)),
        make_bulk_downloads(app_config=app_config, database=database),
        cast("Any", EmptyResolver()),
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
    queued: list[str] = []

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target.target_url)
        return True

    use_theme_work(
        monkeypatch, theme_bulk.BulkThemeWork([item], "{title} theme", index)
    )
    monkeypatch.setattr(theme_bulk, "queue_download", fake_queue)
    bind_stamper(monkeypatch, theme_bulk)

    # Order 1: overturedb first
    context1 = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context1),
        BulkThemeRequest(
            source_order=[ThemeBulkSource.OVERTUREDB, ThemeBulkSource.THEMERRDB]
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    assert queued == ["yt-overture"]
    assert any(
        "Queued Movie - OvertureDB theme" in str(line)
        for line in progress_logs(context1)
    )

    # Order 2: themerrdb first
    queued.clear()
    context2 = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context2),
        BulkThemeRequest(
            source_order=[ThemeBulkSource.THEMERRDB, ThemeBulkSource.OVERTUREDB]
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    assert queued == ["yt-themerr"]
    assert any(
        "Queued Movie - ThemerrDB theme" in str(line)
        for line in progress_logs(context2)
    )


async def test_bulk_theme_falls_back_when_first_source_previously_failed(
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
    queued: list[str] = []

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target.target_url)
        return True

    use_theme_work(
        monkeypatch,
        theme_bulk.BulkThemeWork(
            [item], "{title} theme", index, failed_themes={1: {"yt-overture-failed"}}
        ),
    )
    monkeypatch.setattr(theme_bulk, "queue_download", fake_queue)
    bind_stamper(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=[ThemeBulkSource.OVERTUREDB, ThemeBulkSource.THEMERRDB]
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )
    # Even though overturedb was first, it was failed, so fallback to themerrdb
    assert queued == ["yt-themerr-working"]
    assert any(
        "Queued Movie - ThemerrDB theme" in str(line) for line in progress_logs(context)
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
    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork(items, "{title}"))
    monkeypatch.setattr(theme_bulk, "queue_download", queue)
    bind_stamper(monkeypatch, theme_bulk)

    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[ThemeBulkSource.YOUTUBE_SEARCH]),
        make_bulk_downloads(app_config=app_config, database=database),
        cast("Any", SlowSearch()),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    queued = [line for line in progress_logs(context) if line.startswith("Queued")]
    assert [line.split(" - ")[0] for line in queued] == [
        f"Queued Movie {index}" for index in range(1, 6)
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

    use_theme_work(monkeypatch, theme_bulk.BulkThemeWork([item], "{title}"))
    bind_stamper(monkeypatch, theme_bulk)

    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[ThemeBulkSource.OVERTUREDB]),
        downloads,
        cast("Any", theme_bulk.YouTubeResolver),
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
