"""Source decisions and outcomes in services.art.bulk."""

lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import AsyncMock, Mock

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import ArtFileFacts
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtBulkSource,
    ArtType,
    MediaType,
    RecentUnit,
)
lazy from overture.schemas.art import ArtCandidate, ArtMatchResponse, MatchReference
lazy from overture.schemas.bulk import (
    BulkArtMatchResult,
    BulkMatchArtRequest,
)
lazy from overture.services.art import bulk as art_bulk
lazy from overture.services.art.bulk_work import BulkArtWork
lazy from overture.services.art.matcher import ArtMatchOutcome
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.job_results import page
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import (
    Context,
    art_matcher,
    as_job_context,
    bind_stamper,
    make_bulk_downloads,
    movie_item,
    progress_logs,
    public_index,
    use_art_work,
)
lazy from tests.runtime_helpers import (
    make_local_assets,
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
    matcher = art_matcher(app_config=app_config, database=database)
    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)], index))
    monkeypatch.setattr(matcher, "match_item_art", fail)
    monkeypatch.setattr(art_bulk, "queue_download", queue)
    stamper = bind_stamper(monkeypatch, art_bulk)
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[
                ArtBulkSource.LOCAL_ART_MATCHING,
                ArtBulkSource.OVERTUREDB,
            ]
        ),
        downloads,
        matcher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )
    logs = [str(line) for line in progress_logs(context)]
    target = "Movie (poster)"
    failed = "Local art matching: source unavailable"
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


async def test_bulk_art_uses_source_order_and_skips_local_when_overturedb_matches(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = movie_item()
    queued: list[str] = []

    async def unexpected_local(*_args: object, **_kwargs: object):
        raise AssertionError("local source should not run after OvertureDB matched")

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target.target_url)
        return True

    use_art_work(
        monkeypatch,
        BulkArtWork(
            [(item, ArtType.POSTER, None)],
            public_index(1, poster_url="https://db.example/poster.jpg"),
        ),
    )
    monkeypatch.setattr(art_bulk, "_from_local_matching", unexpected_local)
    monkeypatch.setattr(art_bulk, "queue_download", fake_queue)
    bind_stamper(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[ArtBulkSource.OVERTUREDB, ArtBulkSource.LOCAL_ART_MATCHING]
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert queued == ["https://db.example/poster.jpg"]
    assert progress_logs(context) == ["Queued Movie (poster) - OvertureDB artwork"]
    completed = context.events[-1][1]
    assert completed["queued"] == 1
    results_page = await page(database, str(completed["results_run_id"]), 0, 100)
    assert results_page.items == [
        BulkArtMatchResult(
            title="Movie",
            art_type=ArtType.POSTER,
            source="OvertureDB",
            url="https://db.example/poster.jpg",
            adopted=False,
        ).model_dump(mode="json")
    ]


async def test_bulk_art_overturedb_only_no_matches_when_source_unavailable(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = movie_item()

    async def unexpected_local(*_args: object, **_kwargs: object):
        raise AssertionError("local source should not run when it is not enabled")

    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)]))
    monkeypatch.setattr(art_bulk, "_from_local_matching", unexpected_local)
    bind_stamper(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(source_order=[ArtBulkSource.OVERTUREDB]),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [
        "No match Movie (poster) - OvertureDB has no artwork for it"
    ]
    completed = context.events[-1][1]
    assert completed["no_match"] == 1


@pytest.mark.parametrize(
    ("movies", "line"), [(150, "300 art slots"), (1, "2 art slots")]
)
async def test_bulk_art_targets_without_dataset_art_are_counted_in_one_step(
    movies: int,
    line: str,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Slots no dataset serves are decided while planning, in one line."""

    async def unexpected(*_args: object, **_kwargs: object):
        raise AssertionError("planned targets are never read or matched")

    db_session.add_all(
        MediaItem(
            id=n,
            title=f"Movie {n}",
            media_type=MediaType.MOVIE,
            folder_path=f"/media/Movie {n}",
        )
        for n in range(1, movies + 1)
    )
    await db_session.commit()
    local_assets = make_local_assets(app_config=app_config, database=database)
    monkeypatch.setattr(local_assets, "reconcile", unexpected)
    monkeypatch.setattr(art_bulk, "_from_local_matching", unexpected)
    bind_stamper(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(source_order=[ArtBulkSource.OVERTUREDB]),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=local_assets,
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [
        f"No match {line} - OvertureDB has no artwork for it"
    ]
    planned = context.events[1][1]
    assert planned["total"] == movies * 2
    assert planned["done"] == 0
    completed = context.events[-1][1]
    assert (
        completed["total"] == completed["done"] == completed["no_match"] == movies * 2
    )


async def test_bulk_art_saved_incomplete_selection_queues_download_without_rematch(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    item = movie_item(art={"poster": {"url": "saved-url"}})
    queued: list[str] = []

    async def unexpected_source(*_args: object, **_kwargs: object):
        raise AssertionError("sources should not run for saved incomplete selections")

    async def fake_queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target.target_url)
        return True

    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)]))
    monkeypatch.setattr(art_bulk, "_from_local_matching", unexpected_source)
    monkeypatch.setattr(art_bulk, "queue_download", fake_queue)
    bind_stamper(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(retry_saved_downloads=True),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert queued == ["saved-url"]
    log = progress_logs(context)[-1]
    assert isinstance(log, str)
    assert log == (
        "Queued Movie (poster) - restores the saved selection; local file missing"
    )


async def test_bulk_art_complete_targets_are_skipped_without_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item(art={"poster": {"url": "https://x/poster.jpg", "file_hash": "h"}})

    item.folder_path = str(tmp_path)
    (tmp_path / "poster.jpg").write_bytes(b"existing asset")

    async def unexpected_call(*_args: object, **_kwargs: object):
        raise AssertionError("complete targets should not be matched or downloaded")

    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)]))
    monkeypatch.setattr(art_bulk, "_from_local_matching", unexpected_call)
    monkeypatch.setattr(art_bulk, "queue_download", unexpected_call)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [
        f"Skipped Movie (poster) - {art_bulk.SAVED_SELECTION}"
    ]
    completed = context.events[-1][1]
    assert completed["skipped"] == 1
    assert completed["queued"] == 0


@pytest.mark.parametrize(
    ("match_result", "threshold", "expected"),
    [
        (
            ArtMatchResponse(total_compared=5, prefiltered=3),
            10,
            (
                "No match Movie (poster) - Local art matching: nothing within "
                "distance 10, 3 rejected on size or aspect ratio"
            ),
        ),
        (
            ArtMatchResponse(total_compared=5),
            -1,
            "No match Movie (poster) - Local art matching: no perfect match",
        ),
        (
            ArtMatchResponse(prefiltered=4),
            10,
            (
                "No match Movie (poster) - Local art matching: all 4 candidates "
                "rejected on size or aspect ratio"
            ),
        ),
        (
            ArtMatchResponse(),
            10,
            (
                "No match Movie (poster) - Local art matching: "
                "no candidates returned by enabled artwork providers"
            ),
        ),
        (
            ArtMatchResponse(
                reason="no local file, media-server image or saved URL to compare"
            ),
            10,
            (
                "No match Movie (poster) - Local art matching: no local file, "
                "media-server image or saved URL to compare"
            ),
        ),
        (
            ArtMatchResponse(errors=["Could not read media-server artwork selection"]),
            10,
            (
                "Error Movie (poster) - Local art matching: "
                "Could not read media-server artwork selection"
            ),
        ),
    ],
)
async def test_bulk_art_states_why_local_matching_produced_nothing(
    monkeypatch: pytest.MonkeyPatch,
    match_result: ArtMatchResponse,
    threshold: int,
    expected: str,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    matcher = art_matcher(app_config=app_config, database=database)

    async def fake_match(**_kwargs: object) -> ArtMatchOutcome:
        return ArtMatchOutcome(match_result)

    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)]))
    monkeypatch.setattr(matcher, "match_item_art", fake_match)
    bind_stamper(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[ArtBulkSource.LOCAL_ART_MATCHING], threshold=threshold
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        matcher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [expected]


async def test_bulk_art_says_a_recently_checked_target_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Recently checked slots are decided while planning, in one line."""

    async def unexpected(*_args: object, **_kwargs: object):
        raise AssertionError("recently checked targets are never read or matched")

    db_session.add(movie_item(last_matched_at=utc_now()))
    await db_session.commit()
    local_assets = make_local_assets(app_config=app_config, database=database)
    monkeypatch.setattr(local_assets, "reconcile", unexpected)
    monkeypatch.setattr(art_bulk, "_from_local_matching", unexpected)
    bind_stamper(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(skip_recent_val=1, skip_recent_unit=RecentUnit.DAYS),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=local_assets,
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [
        "Skipped 2 art slots - checked within the last 1 day"
    ]


async def test_bulk_art_single_target_without_dataset_art_has_singular_plurality(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    db_session.add(
        MediaItem(
            id=1, title="Movie", media_type=MediaType.MOVIE, folder_path="/media/Movie"
        )
    )
    await db_session.commit()

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[ArtBulkSource.OVERTUREDB], art_types=[ArtType.POSTER]
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [
        "No match 1 art slot - OvertureDB has no artwork for it"
    ]


@pytest.mark.parametrize(
    ("reference", "reason"),
    [
        ("local_file", "replaces the local file"),
        ("media_server", "compared with the media server's image"),
        ("saved_url", "compared with the saved URL's image"),
        (None, "d=3 from TMDB"),
    ],
)
async def test_local_match_queues_best_candidate_and_reports_incomplete_comparison(
    reference: MatchReference | None,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    matcher = art_matcher(app_config=app_config, database=database)
    response = ArtMatchResponse(
        matches=[
            ArtCandidate(
                url="https://images.test/best.jpg",
                source="TMDB",
                hamming=3,
                width=1000,
                height=1500,
            ),
            ArtCandidate(url="https://images.test/second.jpg", hamming=5),
        ],
        total_compared=2,
        failed=1,
        reference=reference,
    )
    monkeypatch.setattr(
        matcher, "match_item_art", AsyncMock(return_value=ArtMatchOutcome(response))
    )
    queue = AsyncMock(return_value=True)
    monkeypatch.setattr(art_bulk, "queue_download", queue)
    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)]))
    stamper = bind_stamper(monkeypatch, art_bulk)
    context = Context()

    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[ArtBulkSource.LOCAL_ART_MATCHING], threshold=10
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        matcher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert queue.await_count == 1
    assert queue.call_args.args[0] == JobTarget.art(
        1, ArtType.POSTER, "https://images.test/best.jpg"
    )
    assert stamper.checked == [1]
    logs = progress_logs(context)
    assert len(logs) == 1
    assert logs[0].startswith("Queued Movie (poster) - ")
    assert reason in logs[0]
    assert "incomplete comparison: could not compare 1 artwork candidates" in logs[0]
    assert context.events[-1][1]["queued"] == 1


@pytest.mark.parametrize("adopted", [False, True])
async def test_perfect_match_adoption_rechecks_the_file_before_saving_selection(
    adopted: bool,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item()
    matcher = art_matcher(app_config=app_config, database=database)
    local = ArtFileFacts("hash", None, 1000, 1500, 100, 50)
    response = ArtMatchResponse(
        matches=[
            ArtCandidate(
                url="https://images.test/perfect.jpg", source="TMDB", perfect_match=True
            )
        ],
        total_compared=1,
    )
    monkeypatch.setattr(
        matcher,
        "match_item_art",
        AsyncMock(return_value=ArtMatchOutcome(response, local)),
    )
    adopt = AsyncMock(return_value=adopted)
    emit = AsyncMock()
    queue = AsyncMock()
    monkeypatch.setattr(art_bulk, "adopt_art", adopt)
    monkeypatch.setattr(art_bulk, "emit_library_item_upserted", emit)
    monkeypatch.setattr(art_bulk, "queue_download", queue)
    use_art_work(monkeypatch, BulkArtWork([(item, ArtType.POSTER, None)]))
    stamper = bind_stamper(monkeypatch, art_bulk)
    context = Context()

    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[ArtBulkSource.LOCAL_ART_MATCHING], threshold=-1
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        matcher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    adopt.assert_awaited_once()
    assert adopt.call_args.kwargs["verified"] == local
    assert adopt.call_args.kwargs["url"] == "https://images.test/perfect.jpg"
    queue.assert_not_awaited()
    assert emit.await_count == int(adopted)
    assert stamper.checked == ([1] if adopted else [])
    logs = progress_logs(context)
    assert len(logs) == 1
    if adopted:
        assert logs[0] == (
            "Adopted Movie (poster) - perfect match from TMDB is identical to the "
            "local file; selection saved, nothing downloaded"
        )
    else:
        assert logs[0].startswith("Skipped Movie (poster) - the local file changed")


async def test_failed_catalog_comparison_reports_error_without_stamping(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    item = movie_item(
        art={"poster": {"file_hash": "hash", "file_mtime_ns": 100, "file_size": 50}}
    )
    matcher = art_matcher(app_config=app_config, database=database)
    monkeypatch.setattr(
        matcher,
        "identical_to_local",
        AsyncMock(side_effect=ValueError("invalid image")),
    )
    use_art_work(
        monkeypatch,
        BulkArtWork(
            [(item, ArtType.POSTER, None)],
            public_index(1, poster_url="https://images.test/poster.jpg"),
        ),
    )
    stamper = bind_stamper(monkeypatch, art_bulk)
    context = Context()

    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(source_order=[ArtBulkSource.OVERTUREDB]),
        make_bulk_downloads(app_config=app_config, database=database),
        matcher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    assert progress_logs(context) == [
        "Error Movie (poster) - OvertureDB: invalid image"
    ]
    assert stamper.checked == []
    assert context.events[-1][1]["errors"] == 1


@pytest.mark.parametrize("failure_point", ["decision", "stamp"])
async def test_slot_failure_does_not_abort_later_targets(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    items = [movie_item(id=1, title="First"), movie_item(id=2, title="Second")]
    matcher = art_matcher(app_config=app_config, database=database)
    index = public_index(1)
    use_art_work(
        monkeypatch,
        BulkArtWork([(item, ArtType.POSTER, None) for item in items], index),
    )
    stamper = bind_stamper(monkeypatch, art_bulk)
    flush = AsyncMock()
    monkeypatch.setattr(stamper, "flush", flush)
    if failure_point == "stamp":
        monkeypatch.setattr(
            stamper, "add", AsyncMock(side_effect=[OSError("disk unavailable"), None])
        )
    else:
        monkeypatch.setattr(
            type(index), "art_url", Mock(side_effect=[ValueError("invalid slot"), None])
        )
    context = Context()

    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(source_order=[ArtBulkSource.OVERTUREDB]),
        make_bulk_downloads(app_config=app_config, database=database),
        matcher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )

    logs = progress_logs(context)
    assert any(line.startswith("Error First (poster)") for line in logs)
    assert logs[-1] == "No match Second (poster) - OvertureDB has no artwork for it"
    flush.assert_awaited_once()
    assert context.events[-1][1]["errors"] == 1
