"""Exercise the bulk decision matrix against real database rows and files."""

lazy import re
lazy from itertools import product
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import place_local, read_asset, select_art
lazy from overture.db.models.catalog import (
    CatalogItem,
    CatalogItemSeason,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    CURRENT_SELECTION,
    ArtBulkSource,
    ArtType,
    MediaType,
    ServerAsset,
    ServerType,
    ThemeBulkSource,
)
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.matcher import ImageComparison
lazy from overture.services.asset_runs import run as asset_run
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.hashing import compute_bytes_hash
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import (
    CATALOG_BYTES,
    Context,
    art_matcher,
    as_job_context,
    enable_catalog,
    fast_fingerprints,
    make_bulk_downloads,
    no_tags,
    planned_event,
    progress_logs,
    write_existing_asset,
)
lazy from tests.factories import file_hash_of, seed_asset, seed_theme, theme_file_hash
lazy from tests.media_servers import configure, served_item
lazy from tests.runtime_helpers import make_local_assets, unused

#: The words each per-target action's log line starts with and contains.
ACTION_LINES: frozendict[str, tuple[str, str]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "queued": ("Queued ", "OvertureDB"),
        "restored": ("Queued ", "restores the saved selection"),
        "kept_saved": ("Skipped ", "saved selection kept"),
        "kept_theme": ("Skipped ", "kept the theme in place"),
        "kept_art": ("Skipped ", "OvertureDB artwork is a different picture, d=30"),
        "adopted": ("Adopted ", "identical to the local file"),
    }
)

#: Actions planning decides from the database: no line names the target, and
#: only the files of a saved selection are read, before planning.
PLANNED_ACTIONS = frozenset({"set", "no_match", "recent"})


@pytest.mark.parametrize("asset", ["theme", "poster", "background", "season_poster"])
@pytest.mark.parametrize("server", ["plex", "jellyfin", "emby"])
@pytest.mark.parametrize("mode", ["kept", "replaced"])
async def test_catalog_only_state_matrix(
    asset: str,
    server: str,
    mode: str,
    tmp_path: Path,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    """Every combination must produce the right action, log, counters and rows.

    *mode* ranks Current selection first (kept) or below OvertureDB (replaced).

    Cross product: selection, file on disk (identical to the catalog image or
    not), a stale cached presence flag, recent check, catalog absent/empty/
    populated, and media-server identity. Repeat for every asset and server
    adapter. Downloads are never executed and no network is used.
    """
    configure(app_config, type=ServerType(server))
    storage = AssetStorage(app_config=app_config)
    await enable_catalog(db_session)
    expected: dict[str, str] = {}
    on_disk: dict[int, bool] = {}
    cached_flags: dict[int, bool] = {}
    files_read: dict[int, bool] = {}
    queue_targets: dict[int, str] = {}
    cases = product((False, True), repeat=5)
    for number, (flags, public, server_id) in enumerate(
        product(list(cases), ("absent", "empty", "populated"), (False, True)), 1
    ):
        saved, disk, same, cached, recent = flags
        title = f"Case {number:03d}"
        available = seed_case(
            db_session,
            storage,
            tmp_path / title,
            asset,
            number,
            flags,
            public=public,
            server_id=server_id,
        )
        on_disk[number] = disk
        cached_flags[number] = cached
        action = expected_action(
            saved, disk, same, cached, available, recent, asset, mode
        )
        expected[title] = action
        # Before planning, a run reads the files of what slots hold: a saved
        # selection, or a theme in place.
        files_read[number] = action not in PLANNED_ACTIONS or (
            (saved or asset == "theme") and cached
        )
        if action in {"restored", "queued"}:
            source = "saved" if action == "restored" else "public"
            queue_targets[number] = (
                f"{source}-video"
                if asset == "theme"
                else f"https://{source}.test/image.jpg"
            )
    await db_session.commit()
    queued: dict[int, str | None] = {}

    async def queue(target: JobTarget, **_kwargs: Any) -> bool:
        assert target.media_item_id is not None
        queued[target.media_item_id] = target.target_url
        return True

    async def compare(
        url: str, *, fingerprint: str | None, content_hash: str | None
    ) -> ImageComparison:
        assert url == "https://public.test/image.jpg"
        same = content_hash == compute_bytes_hash(CATALOG_BYTES)
        return ImageComparison(distance=0 if same else 30, identical=same)

    monkeypatch.setattr(asset_run, "queue_download", queue)
    monkeypatch.setattr(asset_run, "queue_download", queue)
    context = Context()
    downloads = make_bulk_downloads(app_config=app_config, database=database)
    local_assets = make_local_assets(
        app_config=app_config,
        database=database,
        asset_storage=storage,
        phash=fast_fingerprints(monkeypatch, app_config=app_config),
    )
    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", no_tags
    )
    if asset == "theme":
        await asset_run.run_themes(
            as_job_context(context),
            BulkThemeRequest(
                source_order=order(ThemeBulkSource.OVERTUREDB, mode),
                skip_recent_val=1,
            ),
            downloads=downloads,
            youtube_resolver=unused(YouTubeResolver),
            app_config=app_config,
            local_assets=local_assets,
            database=database,
        )
    else:
        matcher = art_matcher(app_config=app_config, database=database)
        monkeypatch.setattr(matcher, "compare", compare)
        await asset_run.run_art(
            as_job_context(context),
            BulkMatchArtRequest(
                source_order=order(ArtBulkSource.OVERTUREDB, mode),
                art_types=[ArtType(asset)],
                skip_recent_val=1,
            ),
            downloads=downloads,
            art_matcher=matcher,
            art=unused(CollectionArtService),
            local_assets=local_assets,
            app_config=app_config,
            database=database,
        )
    assert queued == queue_targets
    logs = [str(line) for line in progress_logs(context)]
    actions = list(expected.values())
    no_match = actions.count("no_match")
    # Targets decided while planning are reported in one line per reason.
    assert aggregate(logs, "Skipped") == actions.count("set") + actions.count("recent")
    assert aggregate(logs, "No match") == no_match
    for title, action in expected.items():
        assert_item_log(logs, title, action)

    # Planning counts what it reads up to the total, which then never changes.
    assert planned_event(context)["total"] == len(expected)
    completed = context.events[-1][1]
    assert completed["done"] == completed["total"] == len(expected)
    assert completed["log_targets"].get("Queued", 0) == len(queue_targets)
    assert completed["log_targets"].get("Adopted", 0) == actions.count("adopted")
    assert completed["log_targets"].get("Skipped", 0) == sum(
        action == "set" or action.startswith(("kept", "recent")) for action in actions
    )
    assert completed["log_targets"].get("No match", 0) == no_match
    assert (
        completed["log_targets"].get("Downloaded", 0)
        == completed["log_targets"].get("Error", 0)
        == 0
    )

    await assert_rows_match_disk(
        db_session, asset, on_disk, cached_flags, files_read, expected
    )


def seed_case(
    session: AsyncSession,
    storage: AssetStorage,
    folder: Path,
    asset: str,
    number: int,
    flags: tuple[bool, ...],
    *,
    public: str,
    server_id: bool,
) -> bool:
    """Add one case's rows and files; return whether the catalog serves it."""
    saved, disk, same, cached, recent = flags
    folder.mkdir()
    # A saved selection on disk is the file it was downloaded as.
    if asset == "theme":
        written = b"existing theme"
    else:
        written = CATALOG_BYTES if same else b"existing artwork"
    content = compute_bytes_hash(written) if saved and disk else None
    is_season = asset == "season_poster"
    media_type = MediaType.SHOW if is_season else MediaType.MOVIE
    item = seed_theme(
        served_item(
            id=number,
            title=folder.name,
            media_type=media_type,
            tmdb_id=number,
            folder_path=str(folder),
            server_item_id=str(number) if server_id else None,
            last_matched_at=utc_now() if recent else None,
        ),
        "saved-video" if saved and asset == "theme" else None,
        file_hash="cached-hash" if cached and asset == "theme" else None,
        content_hash=content,
    )
    season = (
        Season(
            id=number,
            media_item_id=number,
            season_num=1,
            file_count=1,
            folder_path=str(folder / "Season 01"),
            last_matched_at=item.last_matched_at,
        )
        if is_season
        else None
    )
    if season is not None:
        # A sync places a season's poster in its show's folder.
        place_local(season, (ServerAsset.SEASON_POSTER,), folder=True)
    if asset != "theme":
        owner = season if season is not None else item
        if saved:
            select_art(
                owner,
                ArtType(asset).server_asset,
                PublicArtUrl("https://saved.test/image.jpg"),
            )
        seed_asset(
            owner,
            ArtType(asset),
            file_hash="cached-hash" if cached else None,
            content_hash=content,
            file_mtime_ns=1 if cached else None,
            file_size=1 if cached else None,
        )
    session.add(item)
    if season is not None:
        session.add(season)
    if disk:
        write_existing_asset(storage, folder, asset, season, identical=same)
    available = public == "populated"
    if public == "absent":
        return available
    session.add(
        CatalogItem(
            id=number,
            media_type=media_type,
            tmdb_id=number,
            youtube_id_overturedb="public-video" if available else None,
            poster_url="https://public.test/image.jpg" if available else None,
            background_url="https://public.test/image.jpg" if available else None,
        )
    )
    if available and is_season:
        session.add(
            CatalogItemSeason(
                catalog_item_id=number,
                season_num=1,
                poster_url="https://public.test/image.jpg",
            )
        )
    return available


def order(source: ArtBulkSource | ThemeBulkSource, mode: str) -> list[Any]:
    """The run's source order: *source* below Current selection, or above it."""
    return (
        [CURRENT_SELECTION, source] if mode == "kept" else [source, CURRENT_SELECTION]
    )


def expected_action(
    saved: bool,
    disk: bool,
    same: bool,
    cached: bool,
    available: bool,
    recent: bool,
    asset: str,
    mode: str,
) -> str:
    # Planning finds a saved selection's recorded file in place; one without
    # a record is visited, which reads the disk.
    recorded = saved and cached and disk
    if saved and (mode == "kept" or not available or recent):
        # Nothing replaces it: OvertureDB ranks below it, has nothing, or the
        # target was checked recently, which only a missing file overrides.
        if recorded:
            return "recent" if available and mode == "replaced" else "set"
        return "kept_saved" if disk else "restored"
    if asset == "theme" and cached and disk:
        # Planning reads the recorded theme in place and holds it like a
        # saved selection: kept, unless OvertureDB ranks above it and has one.
        if mode == "kept" or not available:
            return "set"
        return "recent" if recent else "queued"
    if not available:
        return "no_match"
    if recent:
        return "recent"
    if mode == "replaced" or not disk:
        return "queued"
    if asset == "theme":
        return "kept_theme"
    return "adopted" if same else "kept_art"


def aggregate(logs: list[str], outcome: str) -> int:
    """Sum the counts of a run's planning lines for *outcome*."""
    pattern = re.compile(rf"{outcome} (\d+) (?:items?|assets?) - ")
    return sum(int(match[1]) for line in logs if (match := pattern.prefixmatch(line)))


def assert_item_log(logs: list[str], title: str, action: str) -> None:
    lines = [line for line in logs if f"{title} " in line]
    if action in PLANNED_ACTIONS:
        assert lines == []
        return
    prefix, words = ACTION_LINES[action]
    assert len(lines) == 1, lines
    assert lines[0].startswith(prefix + title), lines
    assert words in lines[0], lines


async def assert_rows_match_disk(
    session: AsyncSession,
    asset: str,
    on_disk: dict[int, bool],
    cached_flags: dict[int, bool],
    files_read: dict[int, bool],
    expected: dict[str, str],
) -> None:
    """Targets whose files were read record the disk; the rest are unread.

    A target decided without reading its files keeps its seeded record - a
    presence flag that may be stale and no hash.
    """
    session.expire_all()
    items = {item.id: item for item in (await session.exec(select(MediaItem))).all()}
    seasons = {
        season.media_item_id: season
        for season in (await session.exec(select(Season))).all()
    }
    for number, disk in on_disk.items():
        item = items[number]
        present = disk if files_read[number] else cached_flags[number]
        if asset == "theme":
            assert (theme_file_hash(item) is not None) is present, item.title
            continue
        owner = seasons[number] if asset == "season_poster" else item
        slot = read_asset(owner, ArtType(asset).server_asset)
        assert (file_hash_of(slot) is not None) is present, item.title
        if expected[item.title] == "adopted":
            assert slot.url == "https://public.test/image.jpg"
