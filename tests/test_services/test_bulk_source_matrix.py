"""Every source set and order, against every catalog, file and option state.

Each target's outcome is derived here from the documented rules, independently
of the runners, and every run is compared with it: the planned lines, each
visited target's line, what was queued and the run's counters.
"""

lazy import re
lazy from collections import Counter
lazy from itertools import permutations, product
lazy from pathlib import Path
lazy from typing import Any, NamedTuple, cast

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import ContentFacts, record_content, select_art
lazy from overture.db.models.catalog import CatalogItem
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    CURRENT_SELECTION,
    CURRENT_SELECTION_LABEL,
    ArtBulkSource,
    ArtType,
    CurrentSelection,
    JobStatus,
    JobType,
    MediaType,
    ServerAsset,
    ThemeBulkSource,
)
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.schemas.art import ArtCandidate, ArtMatchResponse
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.schemas.themes import ThemeSearchResult
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.matcher import ArtMatchOutcome, ImageComparison
lazy from overture.services.asset_runs import run as asset_run
lazy from overture.services.asset_runs.plan import (
    KEPT_IN_PLACE,
    NO_SOURCES,
    SAVED_SELECTION,
)
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.hashing import compute_bytes_hash
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import (
    CATALOG_BYTES,
    Context,
    art_matcher,
    as_job_context,
    disable_catalog,
    enable_catalog,
    fast_fingerprints,
    make_bulk_downloads,
    no_tags,
    progress_logs,
    write_existing_asset,
)
lazy from tests.factories import seed_theme
lazy from tests.media_servers import served_item
lazy from tests.runtime_helpers import make_local_assets, unused

CATALOG_URL = "https://public.test/image.jpg"
SAVED_URL = "https://saved.test/image.jpg"
LOCAL_URL = "https://local.test/image.jpg"
RECENT = "checked within the last 1 hour"

#: A line planning wrote for several targets at once.
PLANNED_LINE = re.compile(r"(Skipped|No match) (\d+) (?:items?|assets?) - (.*)")


def orders[T](sources: tuple[T, ...]) -> list[tuple[T | CurrentSelection, ...]]:
    """Every selection of *sources*, none included, in every order, with
    Current selection at every place in it."""
    return [
        (*order[:place], CURRENT_SELECTION, *order[place:])
        for size in range(len(sources) + 1)
        for order in permutations(sources, size)
        for place in range(size + 1)
    ]


def order_id(order: tuple[Any, ...]) -> str:
    return "+".join(str(step) for step in order)


def split[T](order: tuple[T | CurrentSelection, ...]) -> tuple[list[T], list[T]]:
    """The sources above Current selection, which may replace, and every source."""
    place = order.index(CURRENT_SELECTION)
    above = [step for step in order[:place] if step != CURRENT_SELECTION]
    return above, [step for step in order if step != CURRENT_SELECTION]


class Expected(NamedTuple):
    """One target's result: its outcome and reason, and what it queues."""

    outcome: JobOutcome
    reason: str
    #: Decided while planning, so counted in a shared line instead of its own.
    planned: bool = False
    queued: str | None = None


def planned(
    *,
    saved: str | None,
    recent: bool,
    above: bool,
    asked: bool,
    catalog_only: bool,
    offer: str | None,
    misses: list[str],
    enabled: bool,
) -> Expected | None:
    """Return what planning decides from the database, or ``None`` to visit.

    No case stores the facts of a file on disk, so planning takes every saved
    selection's file as missing and visits it to restore the file. *above*
    says a source ranks above Current selection, *asked* that the target asks
    any source, and *catalog_only* that every source of the run is a catalog.
    """
    if saved is not None and not above:
        return None
    if not asked:
        return Expected(JobOutcome.NO_MATCH, NO_SOURCES, planned=True)
    if catalog_only and offer is None:
        if saved is not None:
            return None
        outcome = JobOutcome.NO_MATCH if enabled else JobOutcome.SKIPPED
        return Expected(outcome, "; ".join(misses), planned=True)
    if recent:
        return (
            None
            if saved is not None
            else Expected(JobOutcome.SKIPPED, RECENT, planned=True)
        )
    return None


def kept(
    *, saved: str | None, on_disk: bool, notes: list[str], asked: bool
) -> Expected:
    """What keeping a target's saved selection, or its theme in place, logs."""
    if saved is not None and not on_disk:
        found = "".join(f"; {note}" for note in notes) if asked else ""
        return Expected(
            JobOutcome.QUEUED,
            f"restores the saved selection; local file missing{found}",
            queued=saved,
        )
    holds = "saved selection kept" if saved is not None else "kept the theme in place"
    if asked and notes:
        return Expected(JobOutcome.SKIPPED, f"{holds}: {'; '.join(notes)}")
    return Expected(
        JobOutcome.SKIPPED, SAVED_SELECTION if saved is not None else KEPT_IN_PLACE
    )


def assert_run(
    context: Context,
    expected: dict[str, Expected],
    queued: dict[str, str | None],
    target: str,
) -> None:
    """Compare a run's log, queued downloads and counters with *expected*."""
    logs = progress_logs(context)
    shared = Counter[tuple[str, str]]()
    for line in logs:
        if match := PLANNED_LINE.fullmatch(line):
            shared[match[1], match[3]] += int(match[2])
    assert shared == Counter(
        (str(result.outcome), result.reason)
        for result in expected.values()
        if result.planned
    )
    for title, result in expected.items():
        name = target.format(title=title)
        lines = [line for line in logs if f" {name} - " in line]
        wanted = (
            [] if result.planned else [f"{result.outcome} {name} - {result.reason}"]
        )
        assert lines == wanted, title
    assert queued == {
        title: result.queued
        for title, result in expected.items()
        if result.queued is not None
    }
    outcomes = Counter(result.outcome for result in expected.values())
    completed = context.events[-1][1]
    assert completed["total"] == completed["done"] == len(expected)
    assert completed["log_targets"].get("Queued", 0) == outcomes[JobOutcome.QUEUED]
    assert completed["log_targets"].get("Adopted", 0) == outcomes[JobOutcome.ADOPTED]
    assert completed["log_targets"].get("Skipped", 0) == outcomes[JobOutcome.SKIPPED]
    assert completed["log_targets"].get("No match", 0) == outcomes[JobOutcome.NO_MATCH]
    assert completed["log_targets"].get("Error", 0) == 0


class ArtCase(NamedTuple):
    """One poster slot's state."""

    #: OvertureDB has no entry, an entry without a poster, or the poster.
    catalog: str
    saved: str | None
    #: No local file, one identical to the catalog's poster, or another.
    disk: str
    local_match: bool
    recent: bool


ART_CASES = [
    ArtCase(*state)
    for state in product(
        ("absent", "empty", "served"),
        (None, SAVED_URL, CATALOG_URL),
        ("none", "same", "different"),
        (False, True),
        (False, True),
    )
]


def expected_art(
    case: ArtCase,
    order: tuple[ArtBulkSource | CurrentSelection, ...],
    *,
    enabled: bool,
) -> Expected:
    above, every = split(order)
    current = case.saved is not None
    asked = above if current else every
    offer = CATALOG_URL if enabled and case.catalog == "served" else None
    if not enabled:
        miss = "OvertureDB is disabled"
    elif case.catalog == "absent":
        miss = "OvertureDB has no entry for it"
    else:
        miss = "OvertureDB has no poster for it"
    decided = planned(
        saved=case.saved,
        recent=case.recent,
        above=bool(above),
        asked=bool(asked),
        catalog_only=every == [ArtBulkSource.OVERTUREDB],
        offer=offer,
        misses=[miss],
        enabled=enabled,
    )
    if decided is not None:
        return decided
    on_disk = case.disk != "none"
    replaces = ArtBulkSource.OVERTUREDB in above
    if current and (not above or case.recent):
        return kept(saved=case.saved, on_disk=on_disk, notes=[], asked=False)
    found = asked_art(case, asked, offer=offer, miss=miss, replaces=replaces)
    if isinstance(found, Expected):
        return found
    declined, empty = found
    if current:
        return kept(saved=case.saved, on_disk=on_disk, notes=empty, asked=True)
    notes = "; ".join([*declined, *empty])
    if declined:
        return Expected(
            JobOutcome.SKIPPED,
            f"kept the local file: {notes} (ranking OvertureDB above "
            f"{CURRENT_SELECTION_LABEL} would replace it)",
        )
    return Expected(JobOutcome.NO_MATCH, notes)


def asked_art(
    case: ArtCase,
    sources: list[ArtBulkSource],
    *,
    offer: str | None,
    miss: str,
    replaces: bool,
) -> Expected | tuple[list[str], list[str]]:
    """Return what asking *sources* decides, or what the declining and empty said.

    OvertureDB compares its art with the file on disk unless it *replaces* it.
    """
    on_disk = case.disk != "none"
    replaced = "; replaces the local file" if on_disk else ""
    declined: list[str] = []
    empty: list[str] = []
    for source in sources:
        if source is ArtBulkSource.LOCAL_ART_MATCHING:
            if case.local_match:
                return Expected(
                    JobOutcome.QUEUED, f"d=3 from Fake{replaced}", queued=LOCAL_URL
                )
            empty.append("Local art matching: no similar artwork")
        elif offer is None:
            empty.append(miss)
        elif on_disk and case.saved == offer:
            return Expected(JobOutcome.SKIPPED, asset_run.ALREADY_IN_PLACE)
        elif not on_disk or replaces:
            return Expected(
                JobOutcome.QUEUED, f"OvertureDB artwork{replaced}", queued=offer
            )
        elif case.disk == "same":
            return Expected(
                JobOutcome.ADOPTED,
                "OvertureDB artwork is identical to the local file; "
                "selection saved, nothing downloaded",
            )
        else:
            declined.append("OvertureDB artwork is a different picture, d=30")
    return declined, empty


@pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "disabled"])
@pytest.mark.parametrize("order", orders(tuple(ArtBulkSource)), ids=order_id)
async def test_art_source_matrix(
    order: tuple[ArtBulkSource | CurrentSelection, ...],
    enabled: bool,
    tmp_path: Path,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    storage = AssetStorage(app_config=app_config)
    await (enable_catalog if enabled else disable_catalog)(db_session)
    cases: dict[int, ArtCase] = {}
    expected: dict[str, Expected] = {}
    for number, case in enumerate(ART_CASES, 1):
        title = f"Case {number:03d}"
        cases[number] = case
        expected[title] = expected_art(case, order, enabled=enabled)
        folder = tmp_path / title
        folder.mkdir()
        item = served_item(
            id=number,
            title=title,
            media_type=MediaType.MOVIE,
            tmdb_id=number,
            folder_path=str(folder),
            last_matched_at=utc_now() if case.recent else None,
        )
        if case.saved:
            select_art(item, ServerAsset.POSTER, PublicArtUrl(case.saved))
            if case.disk != "none":
                # The file on disk is the saved selection, as downloaded.
                on_disk = CATALOG_BYTES if case.disk == "same" else b"existing artwork"
                record_content(
                    item, ServerAsset.POSTER, ContentFacts(compute_bytes_hash(on_disk))
                )
        db_session.add(item)
        if case.disk != "none":
            write_existing_asset(
                storage, folder, "poster", None, identical=case.disk == "same"
            )
        if case.catalog != "absent":
            db_session.add(
                CatalogItem(
                    id=number,
                    media_type=MediaType.MOVIE,
                    tmdb_id=number,
                    poster_url=CATALOG_URL if case.catalog == "served" else None,
                )
            )
    await db_session.commit()

    queued: dict[str, str | None] = {}

    async def queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued[f"Case {target.media_item_id:03d}"] = target.target_url
        return True

    async def compare(
        url: str, *, fingerprint: str | None, content_hash: str | None
    ) -> ImageComparison:
        same = url == CATALOG_URL and content_hash == compute_bytes_hash(CATALOG_BYTES)
        return ImageComparison(distance=0 if same else 30, identical=same)

    async def match_item_art(
        item_id: int, art_type: ArtType, *_args: Any, **_kwargs: Any
    ) -> ArtMatchOutcome:
        case = cases[item_id]
        if not case.local_match:
            return ArtMatchOutcome(ArtMatchResponse(reason="no similar artwork"))
        match = ArtCandidate(url=LOCAL_URL, source="Fake", art_type=art_type, hamming=3)
        return ArtMatchOutcome(
            ArtMatchResponse(
                matches=[match],
                total_compared=1,
                reference="local_file" if case.disk != "none" else None,
            )
        )

    monkeypatch.setattr(asset_run, "queue_download", queue)
    matcher = art_matcher(app_config=app_config, database=database)
    monkeypatch.setattr(matcher, "compare", compare)
    monkeypatch.setattr(matcher, "match_item_art", match_item_art)
    context = Context()
    await asset_run.run_art(
        as_job_context(context),
        BulkMatchArtRequest(
            source_order=list(order),
            art_types=[ArtType.POSTER],
            threshold=10,
            skip_recent_val=1,
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        art_matcher=matcher,
        art=unused(CollectionArtService),
        local_assets=make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=storage,
            phash=fast_fingerprints(monkeypatch, app_config=app_config),
        ),
        app_config=app_config,
        database=database,
    )

    assert_run(context, expected, queued, "{title} (poster)")


class ThemeCase(NamedTuple):
    """One item's theme state."""

    #: OvertureDB's own theme: none, an entry without one, one, or one that
    #: failed to download before, which is offered again.
    overturedb: str
    #: The ThemerrDB theme its entry carries: none, one, or one that failed to
    #: download before, which is offered again.
    themerrdb: str
    #: No saved selection, another video, or OvertureDB's own theme.
    saved: str | None
    disk: bool
    youtube: bool
    recent: bool


THEME_CASES = [
    ThemeCase(*state)
    for state in product(
        ("absent", "empty", "served", "failed"),
        ("none", "served", "failed"),
        (None, "other", "overturedb"),
        (False, True),
        (False, True),
        (False, True),
    )
]

#: The search a YouTube source runs for a title without a year.
SEARCH_FORMAT = AppSettings().theme_search_format


def theme_ids(number: int, case: ThemeCase) -> dict[str, str | None]:
    """Return the case's catalog, saved and search video IDs."""
    saved = {None: None, "other": f"saved-{number}", "overturedb": f"ovt-{number}"}
    return {
        "overturedb": f"ovt-{number}"
        if case.overturedb in {"served", "failed"}
        else None,
        "themerrdb": f"tdb-{number}" if case.themerrdb != "none" else None,
        "saved": saved[case.saved],
    }


def theme_miss(
    source: ThemeBulkSource, case: ThemeCase, *, enabled: bool
) -> str | None:
    """Return why one catalog has no usable theme, or ``None`` when it has one."""
    ours = source is ThemeBulkSource.OVERTUREDB
    state = case.overturedb if ours else case.themerrdb
    if not enabled:
        return (
            "OvertureDB is disabled" if ours else "ThemerrDB needs OvertureDB enabled"
        )
    if state in {"served", "failed"}:
        return None
    if not ours:
        return "ThemerrDB has no theme for it"
    entry = case.overturedb != "absent" or case.themerrdb != "none"
    return f"OvertureDB has no {'theme' if entry else 'entry'} for it"


def expected_theme(
    number: int,
    case: ThemeCase,
    order: tuple[ThemeBulkSource | CurrentSelection, ...],
    *,
    enabled: bool,
) -> Expected:
    ids = theme_ids(number, case)
    above, every = split(order)
    # Planning knows a saved selection, not yet a theme in place.
    asked = above if ids["saved"] is not None else every
    offer: str | None = None
    misses: list[str] = []
    for source in (source for source in asked if source.catalog):
        if (miss := theme_miss(source, case, enabled=enabled)) is None:
            offer = ids[source.value]
            break
        misses.append(miss)
    decided = planned(
        saved=ids["saved"],
        recent=case.recent,
        above=bool(above),
        asked=bool(asked),
        catalog_only=all(source.catalog for source in every),
        offer=offer,
        misses=misses,
        enabled=enabled,
    )
    if decided is not None:
        return decided
    current = ids["saved"] is not None or case.disk
    if current and (not above or case.recent):
        return kept(saved=ids["saved"], on_disk=case.disk, notes=[], asked=False)
    found = asked_theme(number, case, above if current else every, enabled=enabled)
    if isinstance(found, Expected):
        return found
    if current:
        return kept(saved=ids["saved"], on_disk=case.disk, notes=found, asked=True)
    return Expected(JobOutcome.NO_MATCH, "; ".join(found))


def asked_theme(
    number: int, case: ThemeCase, sources: list[ThemeBulkSource], *, enabled: bool
) -> Expected | list[str]:
    """Return what asking *sources* decides, or why none did."""
    ids = theme_ids(number, case)
    replaces = "; replaces the local file" if case.disk else ""
    notes: list[str] = []
    for source in sources:
        if source is ThemeBulkSource.YOUTUBE_SEARCH:
            if case.youtube:
                return Expected(
                    JobOutcome.QUEUED,
                    f"YouTube search: Video {number}{replaces}",
                    queued=f"yt-{number}",
                )
            query = SEARCH_FORMAT.replace("{title}", f"Case {number:03d}")
            query = query.replace("{year}", "").strip()
            notes.append(f"YouTube search: no result for {query!r}")
        elif (miss := theme_miss(source, case, enabled=enabled)) is None:
            # The theme on disk already is the source's: nothing to replace.
            if case.disk and ids["saved"] == ids[source.value]:
                return Expected(JobOutcome.SKIPPED, asset_run.ALREADY_IN_PLACE)
            return Expected(
                JobOutcome.QUEUED,
                f"{source.label} theme{replaces}",
                queued=ids[source.value],
            )
        else:
            notes.append(miss)
    return notes


class FakeSearch:
    """Finds a video only for the items whose case has one."""

    def __init__(self, cases: dict[int, ThemeCase]) -> None:
        self.cases = cases

    async def search(self, query: str, limit: int = 10) -> list[ThemeSearchResult]:
        _ = limit
        number = int(query.split()[1])
        if not self.cases[number].youtube:
            return []
        return [ThemeSearchResult(id=f"yt-{number}", title=f"Video {number}")]


@pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "disabled"])
@pytest.mark.parametrize("order", orders(tuple(ThemeBulkSource)), ids=order_id)
async def test_theme_source_matrix(
    order: tuple[ThemeBulkSource | CurrentSelection, ...],
    enabled: bool,
    tmp_path: Path,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    await (enable_catalog if enabled else disable_catalog)(db_session)
    cases: dict[int, ThemeCase] = {}
    expected: dict[str, Expected] = {}
    for number, case in enumerate(THEME_CASES, 1):
        title = f"Case {number:03d}"
        cases[number] = case
        expected[title] = expected_theme(number, case, order, enabled=enabled)
        ids = theme_ids(number, case)
        folder = tmp_path / title
        folder.mkdir()
        if case.disk:
            (folder / "theme.mp3").write_bytes(b"existing theme")
        db_session.add(
            seed_theme(
                served_item(
                    id=number,
                    title=title,
                    media_type=MediaType.MOVIE,
                    tmdb_id=number,
                    folder_path=str(folder),
                    last_matched_at=utc_now() if case.recent else None,
                ),
                ids["saved"],
                # The file on disk is the saved selection, as downloaded.
                content_hash=compute_bytes_hash(b"existing theme")
                if ids["saved"] and case.disk
                else None,
            )
        )
        if case.overturedb != "absent" or case.themerrdb != "none":
            db_session.add(
                CatalogItem(
                    id=number,
                    media_type=MediaType.MOVIE,
                    tmdb_id=number,
                    youtube_id_overturedb=ids["overturedb"],
                    youtube_id_themerrdb=ids["themerrdb"],
                )
            )
    await db_session.commit()
    db_session.add_all(
        DownloadJob(
            media_item_id=number,
            job_type=JobType.THEME,
            target_url=theme_ids(number, case)[source],
            status=JobStatus.FAILED,
            created_at=utc_now(),
        )
        for number, case in cases.items()
        for source, state in (
            ("overturedb", case.overturedb),
            ("themerrdb", case.themerrdb),
        )
        if state == "failed"
    )
    await db_session.commit()

    queued: dict[str, str | None] = {}

    async def queue(target: JobTarget, **_kwargs: Any) -> bool:
        queued[f"Case {target.media_item_id:03d}"] = target.target_url
        return True

    monkeypatch.setattr(asset_run, "queue_download", queue)
    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", no_tags
    )
    context = Context()
    await asset_run.run_themes(
        as_job_context(context),
        BulkThemeRequest(
            source_order=list(order),
            skip_recent_val=1,
        ),
        downloads=make_bulk_downloads(app_config=app_config, database=database),
        youtube_resolver=cast("Any", FakeSearch(cases)),
        app_config=app_config,
        local_assets=make_local_assets(app_config=app_config, database=database),
        database=database,
    )

    assert_run(context, expected, queued, "{title} (theme)")
