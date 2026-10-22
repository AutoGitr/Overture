"""Sidebar item snapshots scope the asset renamer and the server audit."""

lazy from pathlib import Path

lazy import pytest
lazy from pydantic import ValidationError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from overture.repositories.media_items import MediaItemRepository
lazy from overture.schemas.asset_manager import ScanRequest
lazy from overture.schemas.server_audit import ServerAuditRequest
lazy from overture.services.asset_manager import scan
lazy from overture.services.server_audit.work import AuditTarget, plan_audit
lazy from overture.utils.time import utc_now
lazy from tests.factories import MediaItemFactory
lazy from tests.runtime_helpers import make_local_assets, row_id


@pytest.mark.parametrize("model", [ScanRequest, ServerAuditRequest])
@pytest.mark.parametrize(
    "scope",
    [
        {"item_ids": []},
        {"item_ids": [0]},
        {"item_ids": [1], "movie_folders": ["/media/movies"]},
        {"item_ids": [1], "show_folders": ["/media/tv"]},
    ],
)
def test_invalid_item_scopes_are_rejected(
    model: type[ScanRequest | ServerAuditRequest], scope: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(scope)


@pytest.mark.parametrize("model", [ScanRequest, ServerAuditRequest])
def test_item_scopes_are_deduplicated(
    model: type[ScanRequest | ServerAuditRequest],
) -> None:
    assert model(item_ids=[3, 1, 3]).item_ids == [3, 1]


async def test_item_folders_skip_removed_and_folderless_items(
    db_session: AsyncSession, media_item_factory: MediaItemFactory
) -> None:
    movie = media_item_factory(
        id=None, server_item_id="movie", folder_path="/media/movies/Alien"
    )
    show = media_item_factory(
        id=None,
        server_item_id="show",
        media_type=MediaType.SHOW,
        folder_path="/media/tv/Atlanta",
        monitored=False,
    )
    folderless = media_item_factory(id=None, server_item_id="none", folder_path=None)
    removed = media_item_factory(
        id=None,
        server_item_id="removed",
        folder_path="/media/movies/Gone",
        server_removed_at=utc_now(),
    )
    db_session.add_all([movie, show, folderless, removed])
    await db_session.commit()

    folders = await MediaItemRepository(db_session).item_folders(
        [row_id(item) for item in (movie, show, folderless, removed)]
    )

    assert sorted(folders) == [
        ("/media/movies/Alien", "movie"),
        ("/media/tv/Atlanta", "show"),
    ]


def test_item_folder_work_lists_movies_then_shows_by_name(tmp_path: Path) -> None:
    work_path = tmp_path / "scan.sqlite"

    count = scan.stage_item_folders(
        [
            ("/media/tv/Twin Peaks", "show"),
            ("/media/movies/Zodiac", "movie"),
            ("/media/tv/Atlanta", "show"),
            ("/media/movies/Alien", "movie"),
        ],
        work_path,
    )

    assert count == 4
    assert scan.scan_work_batch(work_path, 0) == [
        (Path("/media/movies/Alien"), "movie"),
        (Path("/media/movies/Zodiac"), "movie"),
        (Path("/media/tv/Atlanta"), "show"),
        (Path("/media/tv/Twin Peaks"), "show"),
    ]


async def test_audit_work_covers_only_the_selected_items(
    tmp_path: Path,
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    folders = {name: tmp_path / "movies" / name for name in ("Selected", "Other")}
    for folder in folders.values():
        folder.mkdir(parents=True)
        (folder / "poster.jpg").write_bytes(b"poster")
    items = [
        media_item_factory(
            id=None, server_item_id=name, title=name, folder_path=str(folder)
        )
        for name, folder in folders.items()
    ]
    db_session.add_all(items)
    await db_session.commit()
    selected = row_id(items[0])

    targets = await plan_audit(
        ServerAuditRequest(item_ids=[selected], art_types=[ArtType.POSTER]),
        make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert targets == [AuditTarget(selected, ArtType.POSTER)]
