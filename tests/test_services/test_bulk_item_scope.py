"""Explicit sidebar results stay scoped throughout both assets workflows."""

lazy import pytest
lazy from pydantic import ValidationError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtBulkSource, ArtType, MediaType, ThemeBulkSource
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.repositories.media_items import MediaItemRepository
lazy from overture.schemas.bulk import (
    BulkAssetsArtConfig,
    BulkAssetsRequest,
    BulkAssetsScheduleWrite,
    BulkAssetsThemeConfig,
    BulkMatchArtRequest,
    BulkThemeRequest,
)
lazy from overture.services.art.bulk_work import load_art_batch, plan_bulk_art
lazy from overture.services.bulk_common import SAVED_SELECTION
lazy from overture.services.themes.bulk import load_theme_batch, plan_bulk_themes
lazy from overture.utils.time import utc_now
lazy from tests.factories import MediaItemFactory, SeasonFactory
lazy from tests.runtime_helpers import make_local_assets, row_id
lazy from tests.test_services.test_bulk_public_dataset_prefilter import visits


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"library_ids": []},
        {"item_ids": []},
        {"item_ids": [0]},
        {"item_ids": [-1]},
        {"item_ids": [1], "library_ids": ["movies"]},
    ],
)
def test_invalid_item_scopes_are_rejected(scope: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BulkAssetsRequest.model_validate({**scope, "themes": {}})


def test_item_snapshots_cannot_be_scheduled() -> None:
    with pytest.raises(ValidationError, match="Scheduled assets require"):
        BulkAssetsScheduleWrite(
            name="Snapshot",
            cron_expression="0 3 * * *",
            config=BulkAssetsRequest(item_ids=[1], themes=BulkAssetsThemeConfig()),
        )


@pytest.mark.parametrize("include_unmonitored", [False, True])
async def test_both_workflows_use_only_explicit_items_and_their_seasons(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    *,
    app_config: Settings,
    database: Database,
    include_unmonitored: bool,
) -> None:
    selected = media_item_factory(
        id=None,
        title="Selected",
        media_type=MediaType.SHOW,
        server_item_id="selected",
        library_id="shows",
        monitored=False,
    )
    excluded = media_item_factory(
        id=None,
        title="Excluded",
        media_type=MediaType.SHOW,
        server_item_id="excluded",
        library_id="shows",
        monitored=True,
    )
    removed = media_item_factory(
        id=None,
        title="Removed",
        server_item_id="removed",
        server_removed_at=utc_now(),
    )
    db_session.add_all([selected, excluded, removed])
    await db_session.commit()
    selected_id, excluded_id = row_id(selected), row_id(excluded)
    season = season_factory(
        id=None, media_item_id=selected_id, season_num=1, file_count=1
    )
    db_session.add_all(
        [
            season,
            season_factory(
                id=None, media_item_id=excluded_id, season_num=1, file_count=1
            ),
        ]
    )
    await db_session.commit()

    request = BulkAssetsRequest(
        item_ids=[selected_id, selected_id, row_id(removed), 999999],
        include_unmonitored=include_unmonitored,
        art=BulkAssetsArtConfig(
            art_types=[ArtType.POSTER, ArtType.SEASON_POSTER],
            source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
        ),
        themes=BulkAssetsThemeConfig(source_order=[ThemeBulkSource.YOUTUBE_SEARCH]),
    )
    assert request.item_ids == [selected_id, row_id(removed), 999999]
    art_request, theme_request = request.art_request(), request.theme_request()
    assert art_request is not None
    assert theme_request is not None
    art = await plan_bulk_art(art_request, app_config=app_config, database=database)
    themes = await plan_bulk_themes(
        theme_request, app_config=app_config, database=database
    )
    assert visits(art) == (
        {
            selected_id: (
                (ArtType.POSTER, None),
                (ArtType.SEASON_POSTER, row_id(season)),
            )
        }
        if include_unmonitored
        else {}
    )
    assert visits(themes) == ({selected_id: (None,)} if include_unmonitored else {})
    assert art.total == (2 if include_unmonitored else 0)
    assert not selected.monitored

    repository = MediaItemRepository(db_session)
    assert await repository.list_bulk_targets(item_ids=[]) == []
    assert [item.id for item in await repository.list_bulk_targets(["shows"])] == [
        excluded_id
    ]
    assert {
        item.id
        for item in await repository.list_bulk_targets(
            ["shows"], include_unmonitored=True
        )
    } == {selected_id, excluded_id}


async def test_fully_saved_chunk_does_not_hide_later_missing_slots(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    complete = media_item_factory(
        id=None,
        server_item_id="complete",
        library_id="movies",
        art={"poster": {"url": "https://saved.test/poster.jpg"}},
        youtube_id="saved-video",
    )
    missing = media_item_factory(
        id=None,
        server_item_id="missing",
        library_id="movies",
    )
    db_session.add_all([complete, missing])
    await db_session.commit()
    art_params = BulkMatchArtRequest(
        library_ids=["movies"],
        art_types=[ArtType.POSTER],
        source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
    )
    theme_params = BulkThemeRequest(
        library_ids=["movies"], source_order=[ThemeBulkSource.YOUTUBE_SEARCH]
    )
    art = await plan_bulk_art(
        art_params, app_config=app_config, database=database, chunk=1
    )
    themes = await plan_bulk_themes(
        theme_params, app_config=app_config, database=database, chunk=1
    )
    assert visits(art) == {row_id(missing): ((ArtType.POSTER, None),)}
    assert visits(themes) == {row_id(missing): (None,)}
    saved = {(JobOutcome.SKIPPED, SAVED_SELECTION): 1}
    assert art.decided == themes.decided == saved
    assert art.total == themes.total == 2


async def test_both_workflows_visit_movies_then_shows_by_title(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    # Saved in the opposite order of the listing, so row order cannot pass.
    items = [
        media_item_factory(
            id=None,
            title=title,
            media_type=media_type,
            server_item_id=title,
            library_id="lib",
        )
        for title, media_type in (
            ("Alpha Show", MediaType.SHOW),
            ("Zulu", MediaType.MOVIE),
            ("Beta", MediaType.MOVIE),
        )
    ]
    db_session.add_all(items)
    await db_session.commit()
    item_ids = [row_id(item) for item in items]
    art_params = BulkMatchArtRequest(
        item_ids=item_ids,
        art_types=[ArtType.BACKGROUND, ArtType.POSTER],
        source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
    )
    theme_params = BulkThemeRequest(
        item_ids=item_ids, source_order=[ThemeBulkSource.YOUTUBE_SEARCH]
    )
    local_assets = make_local_assets(app_config=app_config, database=database)

    (art_batch,) = (
        await plan_bulk_art(art_params, app_config=app_config, database=database)
    ).batches()
    (theme_batch,) = (
        await plan_bulk_themes(theme_params, app_config=app_config, database=database)
    ).batches()
    art = await load_art_batch(
        art_params,
        art_batch,
        local_assets=local_assets,
        app_config=app_config,
        database=database,
    )
    themes = await load_theme_batch(
        theme_params,
        list(theme_batch),
        local_assets=local_assets,
        app_config=app_config,
        database=database,
    )

    assert [(item.title, art_type) for item, art_type, _ in art.targets] == [
        ("Beta", ArtType.POSTER),
        ("Beta", ArtType.BACKGROUND),
        ("Zulu", ArtType.POSTER),
        ("Zulu", ArtType.BACKGROUND),
        ("Alpha Show", ArtType.POSTER),
        ("Alpha Show", ArtType.BACKGROUND),
    ]
    assert [item.title for item in themes.items] == ["Beta", "Zulu", "Alpha Show"]


def test_shared_options_reach_both_workers() -> None:
    request = BulkAssetsRequest(
        library_ids=["movies"],
        include_unmonitored=True,
        overwrite_existing=True,
        retry_saved_downloads=True,
        art=BulkAssetsArtConfig(),
        themes=BulkAssetsThemeConfig(),
    )
    for worker in (request.art_request(), request.theme_request()):
        assert worker is not None
        assert worker.include_unmonitored
        assert worker.overwrite_existing
        assert worker.retry_saved_downloads


async def test_bulk_targets_skip_items_without_a_folder(
    db_session: AsyncSession, media_item_factory: MediaItemFactory
) -> None:
    on_disk = media_item_factory(id=None, server_item_id="disk")
    selection_only = media_item_factory(
        id=None, server_item_id=None, folder_path=None, library_id=None
    )
    db_session.add_all([on_disk, selection_only])
    await db_session.commit()

    targets = await MediaItemRepository(db_session).list_bulk_targets(
        item_ids=[row_id(on_disk), row_id(selection_only)]
    )

    assert [item.id for item in targets] == [row_id(on_disk)]
