"""Coverage for season upsert/reconciliation logic."""

lazy from collections.abc import Mapping
lazy from typing import Any

lazy import pytest
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.domain import ArtType, MediaType
lazy from overture.media_servers.adapters import ServerSeason
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.sync import season_sync as module
lazy from overture.services.sync.season_sync import SeasonSynchronizer
lazy from tests.factories import (
    MediaItemFactory,
    SeasonFactory,
)


def _synchronizer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe_results: dict[int, str | None] | None = None,
    app_config: Settings,
) -> tuple[
    SeasonSynchronizer,
    list[tuple[str, int]],
    list[tuple[MediaItem, list[Season]]],
]:
    """Build a real SeasonSynchronizer with its collaborators' methods stubbed.

    Real AssetStorage instances are used (rather than
    duck-typed fakes) so they satisfy SeasonSynchronizer's concrete
    constructor types under static type checking, matching this codebase's
    convention of patching methods on real objects.
    """
    probe_results = probe_results or {}
    probe_calls: list[tuple[str, int]] = []
    refresh_calls: list[tuple[MediaItem, list[Season]]] = []

    asset_storage = AssetStorage(app_config=app_config)

    def fake_probe_season_folder(show_root: str, season_num: int) -> str | None:
        probe_calls.append((show_root, season_num))
        return probe_results.get(season_num)

    monkeypatch.setattr(asset_storage, "probe_season_folder", fake_probe_season_folder)

    return SeasonSynchronizer(), probe_calls, refresh_calls


def _patch_apply_provider_art_url(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_apply(
        owner: MediaItem | Season,
        art_type: ArtType,
        url_val: str | None,
        _resolved: Mapping[str, str],
        *,
        only_missing: bool,
    ) -> bool:
        calls.append(
            {
                "owner": owner,
                "art_type": art_type,
                "url_val": url_val,
                "only_missing": only_missing,
            }
        )
        if url_val:
            write_art_slot(owner, art_type, url=url_val)
            return True
        return False

    monkeypatch.setattr(module, "apply_provider_art_url", fake_apply)
    return calls


async def test_returns_immediately_when_item_has_no_id(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(id=None)
    # Deliberately do not persist, so item.id stays None.
    synchronizer, probe_calls, refresh_calls = _synchronizer(
        monkeypatch, app_config=app_config
    )

    await synchronizer.upsert_seasons(
        db_session, item, [ServerSeason(num=1)], {}, only_missing_art=False
    )

    assert probe_calls == []
    assert refresh_calls == []


async def test_creates_new_seasons_and_applies_art_urls_without_filesystem_io(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        folder_path="/media/Show One",
        server_item_id="show-1",
        library_id="lib-1",
    )
    db_session.add(item)
    await db_session.commit()

    synchronizer, probe_calls, refresh_calls = _synchronizer(
        monkeypatch,
        probe_results={0: "/media/Show One/Specials", 1: None},
        app_config=app_config,
    )
    art_url_calls = _patch_apply_provider_art_url(monkeypatch)

    season_data: list[ServerSeason] = [
        ServerSeason(
            num=0,
            title=None,
            file_count=2,
            poster_url="https://example.test/specials.jpg",
            server_item_id="srv-special",
        ),
        ServerSeason(num=1, title=None, file_count=5, poster_url=None),
    ]

    await synchronizer.upsert_seasons(
        db_session, item, season_data, {}, only_missing_art=False
    )

    seasons = (
        await db_session.exec(
            select(module.Season).where(module.Season.media_item_id == item.id)
        )
    ).all()
    by_num = {s.season_num: s for s in seasons}

    assert by_num[0].title == "Specials"
    assert by_num[0].file_count == 2
    assert by_num[0].folder_path is None
    assert by_num[0].server_item_id == "srv-special"

    assert by_num[1].title == "Season 1"
    assert by_num[1].file_count == 5
    assert by_num[1].folder_path is None  # probe returned None for season 1

    assert probe_calls == []
    assert len(art_url_calls) == 2
    assert refresh_calls == []


@pytest.mark.parametrize("server_item_id", ["new-season-id", None])
async def test_updates_existing_season_without_reprobing_when_path_still_relative(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    monkeypatch: pytest.MonkeyPatch,
    server_item_id: str | None,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        folder_path="/media/Show Two",
        server_item_id="show-2",
        library_id="lib-1",
    )
    db_session.add(item)
    await db_session.commit()

    existing = season_factory(
        id=None,
        media_item_id=item.id,
        season_num=1,
        title="Old Title",
        file_count=1,
        folder_path="/media/Show Two/Season 01",
        server_item_id="old-season-id",
    )
    db_session.add(existing)
    await db_session.commit()

    synchronizer, probe_calls, _refresh_calls = _synchronizer(
        monkeypatch, app_config=app_config
    )
    _patch_apply_provider_art_url(monkeypatch)

    await synchronizer.upsert_seasons(
        db_session,
        item,
        [
            ServerSeason(
                num=1, title="New Title", file_count=9, server_item_id=server_item_id
            )
        ],
        {},
        only_missing_art=True,
    )

    await db_session.refresh(existing)
    assert existing.title == "New Title"
    assert existing.file_count == 9
    assert existing.server_item_id == server_item_id
    # Path was already relative to the show root, so no reprobe was needed.
    assert probe_calls == []


async def test_leaves_folder_inspection_to_detached_refresh(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        folder_path="/media/Show Three",
        server_item_id="show-3",
        library_id="lib-1",
    )
    db_session.add(item)
    await db_session.commit()

    existing = season_factory(
        id=None,
        media_item_id=item.id,
        season_num=1,
        title="Old",
        file_count=1,
        folder_path="/completely/different/path",
    )
    db_session.add(existing)
    await db_session.commit()

    synchronizer, probe_calls, _refresh_calls = _synchronizer(
        monkeypatch,
        probe_results={1: "/media/Show Three/Season 01"},
        app_config=app_config,
    )
    _patch_apply_provider_art_url(monkeypatch)

    await synchronizer.upsert_seasons(
        db_session,
        item,
        [ServerSeason(num=1, file_count=3)],
        {},
        only_missing_art=False,
    )

    assert probe_calls == []
    await db_session.refresh(existing)
    assert existing.folder_path == "/completely/different/path"


async def test_skips_probe_when_item_has_no_folder_path(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        folder_path=None,
        server_item_id="show-4",
        library_id="lib-1",
    )
    db_session.add(item)
    await db_session.commit()

    synchronizer, probe_calls, _refresh_calls = _synchronizer(
        monkeypatch, app_config=app_config
    )
    _patch_apply_provider_art_url(monkeypatch)

    await synchronizer.upsert_seasons(
        db_session,
        item,
        [ServerSeason(num=1, file_count=1)],
        {},
        only_missing_art=False,
    )

    assert probe_calls == []


async def test_seasons_missing_from_new_data_are_zeroed_out(
    db_session: AsyncSession,
    media_item_factory: MediaItemFactory,
    season_factory: SeasonFactory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item = media_item_factory(
        id=None,
        media_type=MediaType.SHOW,
        folder_path="/media/Show Five",
        server_item_id="show-5",
        library_id="lib-1",
    )
    db_session.add(item)
    await db_session.commit()

    stale = season_factory(
        id=None,
        media_item_id=item.id,
        season_num=2,
        title="Season 2",
        file_count=7,
        folder_path="/media/Show Five/Season 02",
    )
    db_session.add(stale)
    await db_session.commit()

    synchronizer, _probe_calls, _refresh_calls = _synchronizer(
        monkeypatch, app_config=app_config
    )
    _patch_apply_provider_art_url(monkeypatch)

    # New sync payload no longer reports season 2 at all.
    await synchronizer.upsert_seasons(
        db_session,
        item,
        [ServerSeason(num=1, file_count=4)],
        {},
        only_missing_art=False,
    )

    await db_session.refresh(stale)
    assert stale.file_count == 0
