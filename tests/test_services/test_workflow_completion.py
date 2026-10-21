"""Completion policies require the same persisted assets as the sidebar."""

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.domain import ITEM_ART_TYPES, ArtType, AutoUnmonitor, MediaType
lazy from overture.services.library.completion import auto_unmonitor_completed


def _art(item: MediaItem) -> None:
    for art_type in ITEM_ART_TYPES:
        write_art_slot(
            item,
            art_type,
            url=f"https://images.test/{art_type}.jpg",
            file_hash="hash",
        )


@pytest.mark.parametrize("policy", list(AutoUnmonitor))
@pytest.mark.parametrize(
    ("art", "theme"), [(False, False), (True, False), (False, True), (True, True)]
)
async def test_completion_policy_matrix(
    db_session: AsyncSession,
    policy: AutoUnmonitor,
    *,
    art: bool,
    theme: bool,
) -> None:
    settings = AppSettings.model_validate({"auto_unmonitor": policy.value})
    item = MediaItem(
        id=901,
        title="Movie",
        media_type=MediaType.MOVIE,
        folder_path="/media/Movie",
        youtube_id="video" if theme else None,
        theme_file_hash="theme-hash" if theme else None,
    )
    if art:
        _art(item)
    db_session.add_all([settings, item])
    await db_session.flush()
    expected = {
        AutoUnmonitor.OFF: False,
        AutoUnmonitor.ART: art,
        AutoUnmonitor.THEME: theme,
        AutoUnmonitor.ART_OR_THEME: art or theme,
        AutoUnmonitor.ART_AND_THEME: art and theme,
    }[policy]
    assert await auto_unmonitor_completed(db_session, item) is expected
    await db_session.commit()
    await db_session.refresh(item)
    assert item.monitored is not expected


@pytest.mark.parametrize("missing", ["url", "file_hash"])
@pytest.mark.parametrize("art_type", ITEM_ART_TYPES)
async def test_partial_art_does_not_unmonitor(
    db_session: AsyncSession,
    missing: str,
    art_type: ArtType,
) -> None:
    item = MediaItem(
        id=901, title="Movie", media_type=MediaType.MOVIE, folder_path="/media/Movie"
    )
    _art(item)
    write_art_slot(item, art_type, **{missing: None})
    db_session.add_all([AppSettings(auto_unmonitor=AutoUnmonitor.ART), item])
    await db_session.flush()
    assert await auto_unmonitor_completed(db_session, item) is False
    assert item.monitored is True


@pytest.mark.parametrize(("youtube_id", "local"), [(None, True), ("video", False)])
async def test_theme_needs_provenance_and_local_file(
    db_session: AsyncSession,
    youtube_id: str | None,
    *,
    local: bool,
) -> None:
    item = MediaItem(
        id=901,
        title="Movie",
        media_type=MediaType.MOVIE,
        folder_path="/media/Movie",
        youtube_id=youtube_id,
        theme_file_hash="theme-hash" if local else None,
    )
    db_session.add_all([AppSettings(auto_unmonitor=AutoUnmonitor.THEME), item])
    await db_session.flush()
    assert await auto_unmonitor_completed(db_session, item) is False


async def test_show_requires_every_season_with_files_including_specials(
    db_session: AsyncSession,
) -> None:
    item = MediaItem(
        id=901, title="Show", media_type=MediaType.SHOW, folder_path="/media/Show"
    )
    _art(item)
    db_session.add_all([AppSettings(auto_unmonitor=AutoUnmonitor.ART), item])
    await db_session.flush()
    # No known local seasons is not proof of complete show artwork.
    assert await auto_unmonitor_completed(db_session, item) is False
    specials = Season(id=902, media_item_id=901, season_num=0, file_count=1)
    season = Season(id=903, media_item_id=901, season_num=1, file_count=5)
    empty = Season(id=904, media_item_id=901, season_num=2, file_count=0)
    write_art_slot(
        season,
        ArtType.SEASON_POSTER,
        url="https://images.test/season.jpg",
        file_hash="hash",
    )
    db_session.add_all([specials, season, empty])
    await db_session.flush()
    assert await auto_unmonitor_completed(db_session, item) is False
    write_art_slot(
        specials,
        ArtType.SEASON_POSTER,
        url="https://images.test/specials.jpg",
        file_hash="hash",
    )
    db_session.add(specials)
    assert await auto_unmonitor_completed(db_session, item) is True
    assert item.monitored is False


async def test_never_remonitors_an_incomplete_item(db_session: AsyncSession) -> None:
    item = MediaItem(id=901, title="Movie", media_type=MediaType.MOVIE, monitored=False)
    db_session.add_all([AppSettings(auto_unmonitor=AutoUnmonitor.ART_AND_THEME), item])
    await db_session.flush()
    assert await auto_unmonitor_completed(db_session, item) is False
    assert item.monitored is False


async def test_an_item_without_a_folder_completes_on_its_selection(
    db_session: AsyncSession,
) -> None:
    item = MediaItem(
        id=901, title="Movie", media_type=MediaType.MOVIE, youtube_id="video"
    )
    db_session.add_all([AppSettings(auto_unmonitor=AutoUnmonitor.THEME), item])
    await db_session.flush()
    assert await auto_unmonitor_completed(db_session, item) is True


async def test_a_policy_read_by_the_caller_is_used_instead_of_the_settings(
    db_session: AsyncSession,
) -> None:
    item = MediaItem(
        id=901, title="Movie", media_type=MediaType.MOVIE, folder_path="/media/Movie"
    )
    _art(item)
    db_session.add_all([AppSettings(auto_unmonitor=AutoUnmonitor.OFF), item])
    await db_session.flush()

    assert (
        await auto_unmonitor_completed(db_session, item, policy=AutoUnmonitor.ART)
        is True
    )
    assert item.monitored is False
