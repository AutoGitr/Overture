"""Exercise the bulk decision matrix against real database rows and files."""

lazy import re
lazy from itertools import product
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import ArtFileFacts, read_art_slot, write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import (
    PublicDatasetItem,
    PublicDatasetSeason,
)
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtBulkSource,
    ArtType,
    MediaType,
    ServerType,
    ThemeBulkSource,
)
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.services.art import bulk as art_bulk
lazy from overture.services.art.phash import PHASH_HEX_LENGTH, PhashService
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes import bulk as theme_bulk
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.audio import ThemeAudioMetadata
lazy from overture.utils.file import compute_bytes_hash
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import (
    Context,
    art_matcher,
    as_job_context,
    make_bulk_downloads,
    progress_logs,
)
lazy from tests.runtime_helpers import make_local_assets, unused

#: The bytes the fake catalog image has; a local file with them is identical.
CATALOG_BYTES = b"catalog artwork"

#: The words each per-target action's log line starts with and contains.
ACTION_LINES: frozendict[str, tuple[str, str]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "queued": ("Queued ", "OvertureDB"),
        "restored": ("Queued ", "restores the saved selection"),
        "kept_saved": ("Skipped ", "saved selection kept"),
        "kept_theme": ("Skipped ", "kept the local theme file"),
        "kept_art": ("Skipped ", "OvertureDB artwork differs from the local file"),
        "adopted": ("Adopted ", "identical to the local file"),
    }
)

#: Actions planning decides from the database: no line names the target, and
#: its files are never read.
PLANNED_ACTIONS = frozenset({"set", "no_match", "recent"})


@pytest.mark.parametrize("asset", ["theme", "poster", "background", "season_poster"])
@pytest.mark.parametrize("server", ["plex", "jellyfin", "emby"])
@pytest.mark.parametrize("mode", ["default", "retry", "overwrite"])
async def test_dataset_only_state_matrix(
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

    Cross product: selection, file on disk (identical to the catalog image or
    not), a stale cached presence flag, recent check, dataset absent/empty/
    populated, and media-server identity. Repeat for every asset and server
    adapter. Downloads are never executed and no network is used.
    """
    app_config.MEDIA_SERVER = ServerType(server)
    storage = AssetStorage(app_config=app_config)
    db_session.add(
        TaskSchedule(
            task_name="public_dataset",
            enabled=True,
            cron_expression="0 0 * * *",
            payload={},
        )
    )
    expected: dict[str, str] = {}
    on_disk: dict[int, bool] = {}
    cached_flags: dict[int, bool] = {}
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
        action = expected_action(saved, disk, same, available, recent, asset, mode)
        expected[title] = action
        if action in {"restored", "queued"}:
            source = "saved" if action == "restored" else "public"
            queue_targets[number] = (
                f"{source}-video"
                if asset == "theme"
                else f"https://{source}.test/image.jpg"
            )
    await db_session.commit()
    queued: dict[int, str] = {}

    async def queue(target: JobTarget, **_kwargs: Any) -> bool:
        assert target.media_item_id is not None
        queued[target.media_item_id] = target.target_url
        return True

    async def identical_to_local(url: str, facts: ArtFileFacts) -> bool:
        assert url == "https://public.test/image.jpg"
        return facts.file_hash == compute_bytes_hash(CATALOG_BYTES)

    monkeypatch.setattr(art_bulk, "queue_download", queue)
    monkeypatch.setattr(theme_bulk, "queue_download", queue)
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
        await theme_bulk.run_bulk_themes(
            as_job_context(context),
            BulkThemeRequest(
                source_order=[ThemeBulkSource.OVERTUREDB],
                skip_recent_val=1,
                overwrite_existing=mode == "overwrite",
                retry_saved_downloads=mode != "default",
            ),
            downloads,
            unused(YouTubeResolver),
            app_config=app_config,
            local_assets=local_assets,
            database=database,
        )
    else:
        matcher = art_matcher(app_config=app_config, database=database)
        monkeypatch.setattr(matcher, "identical_to_local", identical_to_local)
        await art_bulk.run_bulk_art_match(
            as_job_context(context),
            BulkMatchArtRequest(
                source_order=[ArtBulkSource.OVERTUREDB],
                art_types=[ArtType(asset)],
                skip_recent_val=1,
                overwrite_existing=mode == "overwrite",
                retry_saved_downloads=mode != "default",
            ),
            downloads,
            matcher,
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

    # The total is fixed by the first event after started, and never changes.
    totals = {payload.get("total") for _, payload in context.events[1:]}
    assert totals == {len(expected)}
    completed = context.events[-1][1]
    assert completed["done"] == completed["total"] == len(expected)
    assert completed["queued"] == len(queue_targets)
    assert completed["adopted"] == actions.count("adopted")
    assert completed["skipped"] == sum(
        action == "set" or action.startswith(("kept", "recent")) for action in actions
    )
    assert completed["no_match"] == no_match
    assert completed["downloaded"] == completed["errors"] == 0

    await assert_rows_match_disk(db_session, asset, on_disk, cached_flags, expected)


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
    is_season = asset == "season_poster"
    media_type = MediaType.SHOW if is_season else MediaType.MOVIE
    item = MediaItem(
        id=number,
        title=folder.name,
        media_type=media_type,
        tmdb_id=number,
        folder_path=str(folder),
        server_item_id=str(number) if server_id else None,
        theme_file_hash="cached-hash" if cached and asset == "theme" else None,
        youtube_id="saved-video" if saved and asset == "theme" else None,
        last_matched_at=utc_now() if recent else None,
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
    if asset != "theme":
        write_art_slot(
            season if season is not None else item,
            ArtType(asset),
            url="https://saved.test/image.jpg" if saved else None,
            file_hash="cached-hash" if cached else None,
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
        PublicDatasetItem(
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
            PublicDatasetSeason(
                public_dataset_item_id=number,
                season_num=1,
                poster_url="https://public.test/image.jpg",
            )
        )
    return available


def fast_fingerprints(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> PhashService:
    """Fingerprint files without the decoding pool; the matrix never compares."""
    phash = PhashService(app_config=app_config)

    async def fingerprint(_path: str) -> str:
        return "0" * PHASH_HEX_LENGTH

    monkeypatch.setattr(phash, "compute_from_file", fingerprint)
    return phash


async def no_tags(_path: Path) -> ThemeAudioMetadata:
    """Stand in for ffprobe on a file without embedded provenance."""
    return ThemeAudioMetadata(duration=30)


def expected_action(
    saved: bool,
    disk: bool,
    same: bool,
    available: bool,
    recent: bool,
    asset: str,
    mode: str,
) -> str:
    if mode == "default" and saved:
        return "set"
    if mode == "overwrite":
        if not available:
            return "no_match"
        return "recent" if recent else "queued"
    if saved:
        return "kept_saved" if disk else "restored"
    if not available:
        return "no_match"
    if recent:
        return "recent"
    if asset == "theme" and disk:
        return "kept_theme"
    if disk:
        return "adopted" if same else "kept_art"
    return "queued"


def aggregate(logs: list[str], outcome: str) -> int:
    """Sum the counts of a run's planning lines for *outcome*."""
    pattern = re.compile(rf"{outcome} (\d+) (?:items?|art slots?) - ")
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
    expected: dict[str, str],
) -> None:
    """Visited targets' file records equal the disk; planned ones are unread.

    A target planning decided keeps its seeded record - a presence flag that
    may be stale and no hash - because its files were never read.
    """
    session.expire_all()
    items = {item.id: item for item in (await session.exec(select(MediaItem))).all()}
    seasons = {
        season.media_item_id: season
        for season in (await session.exec(select(Season))).all()
    }
    for number, disk in on_disk.items():
        item = items[number]
        visited = expected[item.title] not in PLANNED_ACTIONS
        present = disk if visited else cached_flags[number]
        if asset == "theme":
            assert (item.theme_file_hash is not None) is present, item.title
            continue
        owner = seasons[number] if asset == "season_poster" else item
        slot = read_art_slot(owner, ArtType(asset))
        assert (slot.file_hash is not None) is present, item.title
        if expected[item.title] == "adopted":
            assert slot.url == "https://public.test/image.jpg"


def write_existing_asset(
    storage: AssetStorage,
    folder: Path,
    asset: str,
    season: Season | None,
    *,
    identical: bool,
) -> None:
    if asset == "theme":
        (folder / "theme.mp3").write_bytes(b"existing theme")
        return
    path = Path(
        storage.resolve_art_path(
            str(folder),
            ArtType(asset),
            season_folder_path=season.folder_path if season else None,
            season_num=1 if season else None,
        )
    )
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(CATALOG_BYTES if identical else b"existing artwork")
