"""Asset-manager scan planning and execution services."""

lazy import os
lazy import re
lazy import sqlite3
lazy from collections import defaultdict
lazy from collections.abc import Callable, Collection, Iterator, Sequence
lazy from contextlib import aclosing, closing
lazy from dataclasses import dataclass
lazy from itertools import batched
lazy from pathlib import Path

lazy from ...config import Settings
lazy from ...db.session import Database
lazy from ...domain import (
    ITEM_ART_TYPES,
    ArtType,
    MediaType,
    ServerAsset,
    text_sort_key,
)
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import JobContext, run_managed_job
lazy from ...jobs.tally import AssetScanTally
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...schemas.asset_manager import AssetIssue, ScanRequest
lazy from ...utils.assets import (
    IMAGE_EXTENSIONS,
    ITEM_ASSET_CANDIDATES,
    THEME_FILENAME,
    infer_art_type,
    parse_season_num,
    season_poster_candidates,
    season_poster_filename,
)
lazy from ...utils.concurrency import in_order
lazy from ...utils.errors import public_error_message
lazy from ...utils.image import get_local_image_size
lazy from ...utils.temporary import operation_directory
lazy from ...utils.threads import owned_thread
lazy from ..local_assets.service import LocalAssets

#: The names Overture reads for an item's poster and background.
_ITEM_ART_NAMES = frozenset(
    filename
    for art_type in ITEM_ART_TYPES
    for filename in ITEM_ASSET_CANDIDATES[art_type]
)

SCAN_ERRORS = (OSError, ValueError)

#: Words in a file name that say which slot it fills, as Plex, Kodi and
#: Jellyfin name local artwork. A file without one is only guessed from its
#: shape, so it is flagged as a possible false positive.
_SLOT_WORDS: frozendict[ServerAsset, frozenset[str]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ServerAsset.POSTER: frozenset({"poster", "folder", "cover"}),
        ServerAsset.BACKGROUND: frozenset({"background", "backdrop", "fanart", "art"}),
        ServerAsset.THEME: frozenset({"theme"}),
    }
)
#: Words naming artwork Overture does not manage. A banner or a logo is
#: shaped like a background without being one, so it is never suggested.
_OTHER_ARTWORK_WORDS = frozenset(
    {"banner", "logo", "clearlogo", "clearart", "landscape", "thumb", "disc", "discart"}
)
#: A season's artwork kept in the show folder (``Season01.jpg``,
#: ``season-specials-poster.jpg``): it is the season's, never the show's.
_SEASON_ARTWORK = re.compile(r"season[\s_-]*(?:\d+|specials|all)", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class _Candidate:
    """A file that could fill a slot under its canonical name."""

    entry: os.DirEntry[str]
    width: int = 0
    height: int = 0

    @property
    def stem(self) -> str:
        return Path(self.entry.name).stem

    @property
    def words(self) -> frozenset[str]:
        return frozenset(re.findall(r"[a-z0-9]+", self.stem.casefold()))


def _list(folder: Path) -> list[os.DirEntry[str]]:
    """Return a folder's entries from one ``scandir``, sorted by name.

    Each entry knows whether it is a file or a directory without another
    stat on filesystems that report entry types.
    """
    with os.scandir(folder) as entries:
        return sorted(entries, key=lambda entry: entry.name)


def _image_extension(name: str) -> str:
    """Return the canonical extension for an image: ``.png``, else ``.jpg``."""
    return ".png" if Path(name).suffix.lower() == ".png" else ".jpg"


def _slot_issues(
    folder: Path,
    names: set[str],
    candidates: list[_Candidate],
    *,
    slot: ServerAsset,
    accepted: Sequence[str],
    suggest: Callable[[_Candidate], str],
    known: Callable[[_Candidate], bool],
    season_num: int | None = None,
) -> Iterator[AssetIssue]:
    """Suggest one candidate for a slot; every other one conflicts with it.

    *accepted* are the names Overture reads for the slot. When the folder
    already holds one, renaming any candidate would replace or shadow it, so
    all of them conflict. Otherwise the candidate most clearly named for the
    slot (then the largest) is suggested. *known* says whether a candidate's
    name marks it for the slot; one that is only guessed is flagged.
    """
    if not candidates:
        return
    filled = next((name for name in accepted if name in names), None)
    canonical = {name.casefold() for name in accepted}
    chosen = (
        None
        if filled is not None
        else max(
            candidates,
            key=lambda candidate: (
                candidate.entry.name.casefold() in canonical,
                known(candidate),
                candidate.width * candidate.height,
            ),
        )
    )
    for candidate in candidates:
        suggested_name = suggest(candidate)
        yield AssetIssue(
            folder=str(folder),
            current_path=candidate.entry.path,
            current_filename=candidate.entry.name,
            suggested_path=str(folder / suggested_name),
            suggested_filename=suggested_name,
            type=slot,
            conflict=candidate is not chosen,
            conflict_with=None
            if candidate is chosen
            else filled or (chosen.entry.name if chosen else ""),
            width=candidate.width,
            height=candidate.height,
            potential_false_positive=not known(candidate),
            season_num=season_num,
        )


def _scan_item_art(
    folder: Path, entries: list[os.DirEntry[str]], art_types: Collection[ServerAsset]
) -> Iterator[AssetIssue]:
    """Find misnamed root-level poster/background files in one media folder.

    Files Overture already reads, a season's artwork, and artwork of a kind
    Overture does not manage are left alone; the rest are classified by shape.
    """
    names = {entry.name for entry in entries}
    by_slot: defaultdict[ArtType, list[_Candidate]] = defaultdict(list)
    for entry in entries:
        candidate = _Candidate(entry)
        if (
            Path(entry.name).suffix.lower() not in IMAGE_EXTENSIONS
            or entry.name in _ITEM_ART_NAMES
            or candidate.words & _OTHER_ARTWORK_WORDS
            or _SEASON_ARTWORK.prefixmatch(candidate.stem)
            or not entry.is_file()
        ):
            continue
        width, height = get_local_image_size(Path(entry.path))
        slot = infer_art_type(width, height)
        if slot is not None and slot.server_asset in art_types:
            by_slot[slot].append(_Candidate(entry, width, height))

    # Poster before background, whichever file name sorts first.
    for slot in ITEM_ART_TYPES:
        candidates = by_slot.get(slot)
        if not candidates:
            continue
        slot_words = _SLOT_WORDS[slot.server_asset]
        yield from _slot_issues(
            folder,
            names,
            candidates,
            slot=slot.server_asset,
            accepted=ITEM_ASSET_CANDIDATES[slot],
            suggest=lambda candidate, slot=slot: (
                f"{slot}{_image_extension(candidate.entry.name)}"
            ),
            known=lambda candidate, words=slot_words: bool(candidate.words & words),
        )


def _scan_theme_files(
    folder: Path, entries: list[os.DirEntry[str]]
) -> Iterator[AssetIssue]:
    """Find a misnamed theme among the MP3s in one media folder."""
    return _slot_issues(
        folder,
        {entry.name for entry in entries},
        [
            _Candidate(entry)
            for entry in entries
            if entry.name.lower().endswith(".mp3")
            and entry.name != THEME_FILENAME
            and entry.is_file()
        ],
        slot=ServerAsset.THEME,
        accepted=[THEME_FILENAME],
        suggest=lambda _candidate: THEME_FILENAME,
        known=lambda candidate: bool(candidate.words & _SLOT_WORDS[ServerAsset.THEME]),
    )


def _scan_season_posters(
    entries: list[os.DirEntry[str]], *, app_config: Settings
) -> Iterator[AssetIssue]:
    """Find misnamed season posters under one show folder."""
    for sub in entries:
        season_num = parse_season_num(sub.name)
        if season_num is None or not sub.is_dir():
            continue
        yield from _scan_one_season_folder(
            Path(sub.path), season_num, app_config=app_config
        )


def _scan_one_season_folder(
    sub: Path, season_num: int, *, app_config: Settings
) -> Iterator[AssetIssue]:
    """Find a misnamed poster inside one season folder."""
    entries = _list(sub)
    accepted = season_poster_candidates(app_config.MEDIA_SERVER or "", season_num)
    candidates: list[_Candidate] = []
    for entry in entries:
        candidate = _Candidate(entry)
        if (
            Path(entry.name).suffix.lower() not in IMAGE_EXTENSIONS
            or entry.name in accepted
            or candidate.words & _OTHER_ARTWORK_WORDS
            or not entry.is_file()
        ):
            continue
        width, height = get_local_image_size(Path(entry.path))
        if infer_art_type(width, height) == ArtType.POSTER:
            candidates.append(_Candidate(entry, width, height))

    yield from _slot_issues(
        sub,
        {entry.name for entry in entries},
        candidates,
        slot=ServerAsset.SEASON_POSTER,
        accepted=accepted,
        suggest=lambda candidate: season_poster_filename(
            app_config.MEDIA_SERVER or "",
            season_num,
            _image_extension(candidate.entry.name),
        ),
        known=lambda candidate: bool(
            candidate.words & _SLOT_WORDS[ServerAsset.POSTER]
            or _SEASON_ARTWORK.prefixmatch(candidate.stem)
        ),
        season_num=season_num,
    )


def scan_media_folder(
    folder: Path,
    media_type: str,
    art_types: Collection[ServerAsset],
    *,
    app_config: Settings,
) -> Iterator[AssetIssue]:
    """Scan a single movie/show root-level folder for misnamed assets.

    Issues come in the order results are listed: poster, background, season
    posters, then theme.
    """
    try:
        entries = _list(folder)
    except FileNotFoundError, NotADirectoryError:
        return

    if ServerAsset.POSTER in art_types or ServerAsset.BACKGROUND in art_types:
        yield from _scan_item_art(folder, entries, art_types)
    if ServerAsset.SEASON_POSTER in art_types and media_type == MediaType.SHOW:
        yield from _scan_season_posters(entries, app_config=app_config)
    if ServerAsset.THEME in art_types:
        yield from _scan_theme_files(folder, entries)


#: Folders scanned at once. A folder scan waits on its listing and on reading
#: image headers, which overlaps well; results are still reported in order.
_SCAN_CONCURRENCY = 8

#: Issues carried by one progress event.
_ISSUE_BATCH = 100


async def _scan_folder(
    work: tuple[Path, str], params: ScanRequest, *, app_config: Settings
) -> tuple[Path, list[AssetIssue] | Exception]:
    """Return a folder with its issues, or with the error that stopped its scan."""
    folder, media_type = work
    try:
        return folder, await owned_thread(
            lambda: list(
                scan_media_folder(
                    folder, media_type, params.art_types, app_config=app_config
                )
            )
        )
    except SCAN_ERRORS as exc:
        return folder, exc


async def run_scan(
    params: ScanRequest,
    context: JobContext,
    *,
    app_config: Settings,
    local_assets: LocalAssets,
    database: Database,
    config_dir: Path,
) -> None:
    """Scan the selected roots' item folders, or the selected items' folders.

    Planning refreshes the scope's recorded file state and stages every folder,
    so the total is fixed before the first folder is scanned.
    """
    tally = AssetScanTally()

    async with run_managed_job(
        context,
        tally,
        database=database,
        catch=SCAN_ERRORS,
        terminal_extras=lambda t: {"total_folders": t.total},
    ) as job:
        await job.started()
        await local_assets.reconcile(
            item_ids=params.item_ids,
            roots_by_media_type=None
            if params.item_ids is not None
            else {
                MediaType.MOVIE: params.movie_folders,
                MediaType.SHOW: params.show_folders,
            },
            source="assets.scan",
        )
        with operation_directory(config_dir) as directory:
            work_path = directory / "scan.sqlite"
            if params.item_ids is None:
                total = await owned_thread(
                    build_scan_work,
                    params.movie_folders,
                    params.show_folders,
                    work_path,
                )
            else:
                async with database.read_session() as session:
                    item_folders = await MediaItemRepository(session).item_folders(
                        params.item_ids
                    )
                total = await owned_thread(stage_item_folders, item_folders, work_path)
            await job.planned(total)
            offset = 0
            while not job.stop_requested():
                work = await owned_thread(scan_work_batch, work_path, offset)
                if not work:
                    break
                async with aclosing(
                    in_order(
                        work,
                        lambda folder: _scan_folder(
                            folder, params, app_config=app_config
                        ),
                        limit=_SCAN_CONCURRENCY,
                    )
                ) as scanned:
                    async for folder, found in scanned:
                        if job.stop_requested():
                            break
                        if isinstance(found, Exception):
                            await job.report(
                                JobOutcome.ERROR,
                                folder.name,
                                public_error_message(found),
                                issues=[],
                            )
                            continue
                        first, *rest = list(
                            batched(found, _ISSUE_BATCH, strict=False)
                        ) or [()]
                        await job.report(
                            JobOutcome.CHECKED,
                            folder.name,
                            f"{len(found)} issue{'s' if len(found) != 1 else ''} found"
                            if found
                            else "no issues found",
                            issues=tally.collect(*first),
                        )
                        for issues in rest:
                            await job.progress(issues=tally.collect(*issues))

                offset += len(work)


def _create_scan_work(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE folders (path TEXT, kind TEXT, root_order INTEGER, name TEXT)"
    )


def stage_item_folders(item_folders: list[tuple[str, str]], database: Path) -> int:
    """Stage item folders on disk, movies first, then by folder name."""
    with closing(sqlite3.connect(database)) as connection:
        _create_scan_work(connection)
        connection.executemany(
            "INSERT INTO folders VALUES (?, ?, ?, ?)",
            (
                (path, kind, 0 if kind == "movie" else 1, Path(path).name.casefold())
                for path, kind in item_folders
            ),
        )
        connection.commit()
        return len(item_folders)


def build_scan_work(
    movie_folders: list[str], show_folders: list[str], database: Path
) -> int:
    """Stage directory names on disk, preserving stable presentation order."""
    with closing(sqlite3.connect(database)) as connection:
        _create_scan_work(connection)
        count = 0
        roots = [(root, "movie") for root in sorted(movie_folders, key=text_sort_key)]
        roots.extend((root, "show") for root in sorted(show_folders, key=text_sort_key))
        for order, (root, kind) in enumerate(roots):
            try:
                children = os.scandir(root)
            except FileNotFoundError, NotADirectoryError:
                continue
            with children:
                for child in children:
                    if child.is_dir():
                        connection.execute(
                            "INSERT INTO folders VALUES (?, ?, ?, ?)",
                            (child.path, kind, order, child.name.casefold()),
                        )
                        count += 1
        connection.commit()
        return count


def scan_work_batch(database: Path, offset: int) -> list[tuple[Path, str]]:
    """Read at most one hundred staged folder names."""
    with closing(sqlite3.connect(database)) as connection:
        return [
            (Path(path), kind)
            for path, kind in connection.execute(
                "SELECT path, kind FROM folders "
                "ORDER BY root_order, name, path LIMIT 100 OFFSET ?",
                (offset,),
            )
        ]
