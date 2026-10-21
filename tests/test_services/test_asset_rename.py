"""Asset rename validation, filesystem outcomes, and snapshot updates."""

lazy from collections.abc import Collection
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerAsset
lazy from overture.schemas.asset_manager import RenameItem, RenameRequest
lazy from overture.services.asset_manager import service
lazy from overture.services.asset_manager.service import AssetManagerService
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.errors import PublicServiceError
lazy from overture.ws.state import BackgroundJobRegistry
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import NoopProviderRegistry, make_local_assets


def _asset_service(
    jobs: BackgroundJobRegistry,
    publisher: NullEventPublisher,
    *,
    app_config: Settings,
    database: Database,
    config_dir: Path,
    local_assets: LocalAssets | None = None,
    provider: object | None = None,
) -> AssetManagerService:
    return AssetManagerService(
        background_jobs=jobs,
        publisher=publisher,
        app_config=app_config,
        config_dir=config_dir,
        local_assets=local_assets
        or make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=AssetStorage(app_config=app_config),
        ),
        provider_registry=NoopProviderRegistry(provider),
        database=database,
    )


async def _rename(
    asset_service: AssetManagerService,
    jobs: BackgroundJobRegistry,
    *renames: tuple[Path, Path],
) -> list[str]:
    """Rename files the last scan suggested, returning each outcome's status."""
    items = [
        RenameItem(current_path=str(current), suggested_path=str(suggested))
        for current, suggested in renames
    ]
    jobs.asset_scan.save_snapshot(
        "assets.scan.completed",
        {"finished_at": "scan-1", "issues": [item.model_dump() for item in items]},
    )
    response = await asset_service.rename_assets(
        RenameRequest(snapshot_finished_at="scan-1", renames=items)
    )
    return [result.status for result in response.results]


def _names(folder: Path) -> list[str]:
    """Return the names in *folder* as the filesystem spells them."""
    return sorted(path.name for path in folder.iterdir())


class RefreshingProvider:
    def __init__(self) -> None:
        self.refreshed: list[tuple[str, list[str]]] = []

    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        self.refreshed.append((item_id, sorted(unlock)))


async def test_rename_batch_preserves_conflicts_and_records_success(
    tmp_path: Path,
    db_session: AsyncSession,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    source = tmp_path / "cover.jpg"
    target = tmp_path / "poster.jpg"
    source.write_bytes(b"poster")
    conflict = tmp_path / "fanart.jpg"
    conflict.write_bytes(b"replacement")
    background = tmp_path / "background.jpg"
    background.write_bytes(b"existing")
    publisher = NullEventPublisher()
    jobs = BackgroundJobRegistry(publisher)
    jobs.asset_scan.save_snapshot(
        "assets.scan.completed",
        {
            "finished_at": "scan-1",
            "issues": [
                {"current_path": str(source), "suggested_path": str(target)},
                {
                    "current_path": str(conflict),
                    "suggested_path": str(background),
                },
            ],
        },
    )

    asset_service = _asset_service(
        jobs,
        publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    response = await asset_service.rename_assets(
        RenameRequest(
            snapshot_finished_at="scan-1",
            renames=[
                RenameItem(current_path=str(source), suggested_path=str(target)),
                RenameItem(current_path=str(conflict), suggested_path=str(background)),
            ],
        ),
    )

    assert [result.status for result in response.results] == ["renamed", "conflict"]
    assert target.read_bytes() == b"poster"
    assert not source.exists()
    assert conflict.read_bytes() == b"replacement"
    assert background.read_bytes() == b"existing"
    assert jobs.asset_scan.last_payload is not None
    assert jobs.asset_scan.last_payload["issues"][0]["renamed"] is True


@pytest.mark.parametrize(
    ("current_name", "suggested_name", "reason"),
    [
        ("", "poster.jpg", "Missing paths"),
        ("cover.jpg", "", "Missing paths"),
        ("../outside.jpg", "poster.jpg", "Unauthorized current path"),
        ("cover.jpg", "../poster.jpg", "Unauthorized suggested path"),
        ("cover.jpg", "movie.mkv", "canonical asset name"),
        ("cover.jpg", "nested/poster.jpg", "between directories"),
        ("movie.mkv", "poster.jpg", "Unsupported source file extension"),
        ("missing.jpg", "poster.jpg", "Source not found"),
    ],
)
async def test_invalid_renames_leave_files_untouched(
    tmp_path: Path,
    db_session: AsyncSession,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    current_name: str,
    suggested_name: str,
    reason: str,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    (tmp_path / "nested").mkdir()
    source = tmp_path / "cover.jpg"
    source.write_bytes(b"original")
    (tmp_path / "movie.mkv").write_bytes(b"media")
    publisher = NullEventPublisher()
    jobs = BackgroundJobRegistry(publisher)
    rename = RenameItem(
        current_path=str(tmp_path / current_name) if current_name else "",
        suggested_path=str(tmp_path / suggested_name) if suggested_name else "",
    )
    jobs.asset_scan.save_snapshot(
        "assets.scan.completed",
        {"finished_at": "scan-1", "issues": [rename.model_dump()]},
    )
    asset_service = _asset_service(
        jobs,
        publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    response = await asset_service.rename_assets(
        RenameRequest(
            snapshot_finished_at="scan-1",
            renames=[rename],
        ),
    )
    result = response.results[0]
    assert result.status == "error"
    assert reason in (result.reason or "")
    assert source.read_bytes() == b"original"
    assert not (tmp_path / "poster.jpg").exists()


async def test_rename_reports_filesystem_failure_without_changing_source(
    tmp_path: Path,
    db_session: AsyncSession,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    def fail_rename(*_args: object) -> None:
        raise OSError("filesystem unavailable")

    source = tmp_path / "cover.jpg"
    source.write_bytes(b"original")
    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    monkeypatch.setattr(type(source), "rename", fail_rename)
    publisher = NullEventPublisher()
    jobs = BackgroundJobRegistry(publisher)
    rename = RenameItem(
        current_path=str(source),
        suggested_path=str(tmp_path / "poster.jpg"),
    )
    jobs.asset_scan.save_snapshot(
        "assets.scan.completed",
        {"finished_at": "scan-1", "issues": [rename.model_dump()]},
    )
    asset_service = _asset_service(
        jobs,
        publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    response = await asset_service.rename_assets(
        RenameRequest(
            snapshot_finished_at="scan-1",
            renames=[rename],
        ),
    )
    assert response.results[0].status == "error"
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize("symlink_source", [True, False])
async def test_rename_does_not_follow_source_or_destination_symlinks(
    tmp_path: Path,
    db_session: AsyncSession,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    symlink_source: bool,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    original = tmp_path / "original.jpg"
    original.write_bytes(b"original")
    source = tmp_path / "cover.jpg"
    target = tmp_path / "poster.jpg"
    try:
        if symlink_source:
            source.symlink_to(original)
        else:
            source.write_bytes(b"source")
            target.symlink_to(tmp_path / "missing.jpg")
    except OSError:
        pytest.skip("Filesystem does not allow symlink creation")

    publisher = NullEventPublisher()
    jobs = BackgroundJobRegistry(publisher)
    rename = RenameItem(current_path=str(source), suggested_path=str(target))
    jobs.asset_scan.save_snapshot(
        "assets.scan.completed",
        {"finished_at": "scan-1", "issues": [rename.model_dump()]},
    )
    asset_service = _asset_service(
        jobs,
        publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    response = await asset_service.rename_assets(
        RenameRequest(
            snapshot_finished_at="scan-1",
            renames=[rename],
        ),
    )

    assert response.results[0].status == ("error" if symlink_source else "conflict")
    assert original.read_bytes() == b"original"
    assert source.read_bytes() == (b"original" if symlink_source else b"source")
    if not symlink_source:
        assert target.is_symlink()


async def test_rename_rejects_paths_not_returned_by_the_scan(
    tmp_path: Path,
    db_session: AsyncSession,
    database: Database,
    *,
    app_config: Settings,
) -> None:
    authorised = tmp_path / "authorised.jpg"
    forged = tmp_path / "forged.jpg"
    target = tmp_path / "poster.jpg"
    forged.write_bytes(b"unchanged")
    publisher = NullEventPublisher()
    jobs = BackgroundJobRegistry(publisher)
    jobs.asset_scan.save_snapshot(
        "assets.scan.completed",
        {
            "finished_at": "scan-1",
            "issues": [
                {
                    "current_path": str(authorised),
                    "suggested_path": str(target),
                }
            ],
        },
    )

    asset_service = _asset_service(
        jobs,
        publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    with pytest.raises(PublicServiceError) as exc_info:
        await asset_service.rename_assets(
            RenameRequest(
                snapshot_finished_at="scan-1",
                renames=[
                    RenameItem(current_path=str(forged), suggested_path=str(target))
                ],
            ),
        )

    assert exc_info.value.status_code == 409
    assert forged.read_bytes() == b"unchanged"


async def test_a_case_only_rename_succeeds_on_any_filesystem(
    tmp_path: Path,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    movie = tmp_path / "Movie"
    movie.mkdir()
    (movie / "Poster.jpg").write_bytes(b"poster")
    (movie / "Theme.MP3").write_bytes(b"theme")
    jobs = BackgroundJobRegistry(NullEventPublisher())
    asset_service = _asset_service(
        jobs,
        NullEventPublisher(),
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )

    statuses = await _rename(
        asset_service,
        jobs,
        (movie / "Poster.jpg", movie / "poster.jpg"),
        (movie / "Theme.MP3", movie / "theme.mp3"),
    )

    assert statuses == ["renamed", "renamed"]
    assert _names(movie) == ["poster.jpg", "theme.mp3"]


async def test_a_rename_never_leaves_a_slot_in_two_image_formats(
    tmp_path: Path,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    (tmp_path / "cover.jpg").write_bytes(b"cover")
    (tmp_path / "poster.png").write_bytes(b"existing")
    jobs = BackgroundJobRegistry(NullEventPublisher())
    asset_service = _asset_service(
        jobs,
        NullEventPublisher(),
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )

    statuses = await _rename(
        asset_service, jobs, (tmp_path / "cover.jpg", tmp_path / "poster.jpg")
    )

    assert statuses == ["conflict"]
    assert (tmp_path / "cover.jpg").read_bytes() == b"cover"
    assert not (tmp_path / "poster.jpg").exists()


async def test_renames_refresh_the_owning_item_and_its_server_copy(
    tmp_path: Path,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def roots(_session: AsyncSession) -> list[Path]:
        return [tmp_path]

    monkeypatch.setattr(service, "require_trusted_media_roots", roots)
    show = tmp_path / "Show"
    season = show / "Season 01"
    season.mkdir(parents=True)
    (show / "cover.jpg").write_bytes(b"poster")
    (season / "folder.jpg").write_bytes(b"season poster")
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=7,
                media_type=MediaType.SHOW,
                title="Show",
                folder_path=str(show),
                server_item_id="plex-7",
            )
        )
    local_assets = make_local_assets(app_config=app_config, database=database)
    reconciled: list[dict[str, Any]] = []

    async def reconcile(**kwargs: Any) -> None:
        reconciled.append(kwargs)

    monkeypatch.setattr(local_assets, "reconcile", reconcile)
    provider = RefreshingProvider()
    jobs = BackgroundJobRegistry(NullEventPublisher())
    asset_service = _asset_service(
        jobs,
        NullEventPublisher(),
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
        local_assets=local_assets,
        provider=provider,
    )

    statuses = await _rename(
        asset_service,
        jobs,
        (show / "cover.jpg", show / "poster.jpg"),
        (season / "folder.jpg", season / "Season01.jpg"),
    )

    assert statuses == ["renamed", "renamed"]
    # The season folder's rename refreshes the show's records too.
    assert reconciled == [{"item_ids": {7}, "source": "assets.rename"}]
    # The show poster is unlocked; the season poster is not the show's.
    assert provider.refreshed == [("plex-7", ["poster"])]
