"""Coverage for refreshing local file records across a scope of items."""

lazy from pathlib import Path

lazy import pytest
lazy from PIL import Image
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from tests.runtime_helpers import make_local_assets
lazy from tests.test_services.test_bulk_state_matrix import fast_fingerprints


async def test_reconcile_records_item_and_season_art_only_inside_the_roots(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    movie = tmp_path / "movies" / "Movie"
    show = tmp_path / "tv" / "Show"
    outside = tmp_path / "other" / "Outside"
    for folder in (movie, show / "Season 01", outside):
        folder.mkdir(parents=True)
    for poster in (
        movie / "poster.jpg",
        show / "Season 01" / "Season01.jpg",
        outside / "poster.jpg",
    ):
        Image.new("RGB", (100, 150)).save(poster)
    db_session.add_all(
        [
            MediaItem(
                id=1, media_type=MediaType.MOVIE, title="Movie", folder_path=str(movie)
            ),
            MediaItem(
                id=2, media_type=MediaType.SHOW, title="Show", folder_path=str(show)
            ),
            MediaItem(
                id=3,
                media_type=MediaType.MOVIE,
                title="Outside",
                folder_path=str(outside),
            ),
            Season(id=20, media_item_id=2, season_num=1),
        ]
    )
    await db_session.commit()
    local_assets = make_local_assets(
        app_config=app_config,
        database=database,
        phash=fast_fingerprints(monkeypatch, app_config=app_config),
    )

    await local_assets.reconcile(
        roots_by_media_type={
            MediaType.MOVIE: [str(tmp_path / "movies")],
            MediaType.SHOW: [str(tmp_path / "tv")],
        },
        source="test",
    )

    async with database.read_session() as session:
        recorded = {
            item_id: read_art_slot(row, ArtType.POSTER).file_hash
            for item_id in (1, 3)
            if (row := await session.get(MediaItem, item_id)) is not None
        }
        season = await session.get(Season, 20)
    assert recorded[1] is not None
    assert recorded[3] is None
    assert season is not None
    assert season.folder_path == str(show / "Season 01")
    assert read_art_slot(season, ArtType.SEASON_POSTER).file_hash is not None
