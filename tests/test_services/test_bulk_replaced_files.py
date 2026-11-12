"""Assets restores a saved selection whose file was deleted or replaced outside it."""

lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import select_art
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtBulkSource, ArtType, MediaType, ThemeBulkSource
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.services.art import bulk as art_bulk
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.bulk_common import SAVED_SELECTION
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes import bulk as theme_bulk
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.file import compute_bytes_hash
lazy from tests.bulk_helpers import (
    Context,
    art_matcher,
    as_job_context,
    fast_fingerprints,
    make_bulk_downloads,
    no_tags,
    progress_logs,
)
lazy from tests.factories import seed_art_slot
lazy from tests.runtime_helpers import make_local_assets, unused

SAVED_URL = PublicArtUrl("https://saved.test/poster.jpg")
WRITTEN = b"the saved poster as Overture wrote it"
REPLACED = b"a poster another program wrote"

#: What each file on disk is, against the one Overture recorded for the selection.
CASES = ("unchanged", "replaced", "replaced since the last refresh", "deleted")


def _seed(
    session: AsyncSession, folder: Path, file_name: str, case: str
) -> tuple[MediaItem, dict[str, Any]]:
    """Add a movie whose file Overture wrote, changed as *case* says.

    Returns:
        The movie, and the file facts the last refresh recorded for it.
    """
    folder.mkdir()
    path = folder / file_name
    data = REPLACED if case == "replaced" else WRITTEN
    path.write_bytes(data)
    recorded = {
        "file_hash": compute_bytes_hash(data),
        "file_mtime_ns": path.stat().st_mtime_ns,
        "file_size": len(data),
    }
    if case == "replaced since the last refresh":
        path.write_bytes(REPLACED + b" again")
    elif case == "deleted":
        path.unlink()
    item = MediaItem(
        id=1, title="Movie", media_type=MediaType.MOVIE, folder_path=str(folder)
    )
    session.add(item)
    return item, recorded


def _local_assets(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> LocalAssets:
    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", no_tags
    )
    return make_local_assets(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        phash=fast_fingerprints(monkeypatch, app_config=app_config),
    )


def _capture_queue(monkeypatch: pytest.MonkeyPatch, module: object) -> list[str]:
    queued: list[str] = []

    async def queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(str(target.target_url))
        return True

    monkeypatch.setattr(module, "queue_download", queue)
    return queued


def _expected_lines(case: str, target: str, file: str) -> list[str]:
    if case == "unchanged":
        noun = "art slot" if file == "file" else "item"
        return [f"Skipped 1 {noun} - {SAVED_SELECTION}"]
    how = "missing" if case == "deleted" else "replaced outside Overture"
    return [f"Queued {target} - restores the saved selection; local {file} {how}"]


@pytest.mark.parametrize("case", CASES)
async def test_a_saved_poster_is_restored_unless_its_file_is_the_one_overture_wrote(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item, recorded = _seed(db_session, tmp_path / "Movie", "poster.jpg", case)
    select_art(item, ArtType.POSTER, SAVED_URL)
    seed_art_slot(
        item, ArtType.POSTER, selection_hash=compute_bytes_hash(WRITTEN), **recorded
    )
    await db_session.commit()
    queued = _capture_queue(monkeypatch, art_bulk)

    context = Context()
    await art_bulk.run_bulk_art_match(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
            art_types=[ArtType.POSTER],
        ),
        make_bulk_downloads(app_config=app_config, database=database),
        art_matcher(app_config=app_config, database=database),
        art=unused(CollectionArtService),
        local_assets=_local_assets(
            monkeypatch, app_config=app_config, database=database
        ),
        app_config=app_config,
        database=database,
    )

    assert queued == ([] if case == "unchanged" else [SAVED_URL])
    assert progress_logs(context) == _expected_lines(case, "Movie (poster)", "file")


@pytest.mark.parametrize("case", CASES)
async def test_a_saved_theme_is_restored_unless_its_file_is_the_one_overture_wrote(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    item, recorded = _seed(db_session, tmp_path / "Movie", "theme.mp3", case)
    item.youtube_id = "savedVideo1"
    item.theme_file_hash = recorded["file_hash"]
    item.theme_file_mtime_ns = recorded["file_mtime_ns"]
    item.theme_file_size = recorded["file_size"]
    item.theme_file_duration = 30
    item.theme_selection_hash = compute_bytes_hash(WRITTEN)
    await db_session.commit()
    queued = _capture_queue(monkeypatch, theme_bulk)

    context = Context()
    await theme_bulk.run_bulk_themes(
        as_job_context(context),
        BulkThemeRequest(source_order=[ThemeBulkSource.YOUTUBE_SEARCH]),
        make_bulk_downloads(app_config=app_config, database=database),
        unused(YouTubeResolver),
        app_config=app_config,
        local_assets=_local_assets(
            monkeypatch, app_config=app_config, database=database
        ),
        database=database,
    )

    assert queued == ([] if case == "unchanged" else ["savedVideo1"])
    assert progress_logs(context) == _expected_lines(case, "Movie", "theme file")
