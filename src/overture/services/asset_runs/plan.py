"""What an Assets run decides on, and the plan that orders it.

A target is one asset of a title, a season or a collection. Every target in
the run's scope is planned before the first is visited: decided from the
database alone, or kept, as IDs, for a visit that reads its files and asks
its sources. Titles are visited before collections, each by title.
"""

lazy from collections import Counter, defaultdict
lazy from collections.abc import AsyncGenerator, Iterator, Sequence
lazy from dataclasses import dataclass, field
lazy from datetime import datetime, timedelta
lazy from itertools import batched

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.ledger import Selection, missing_deliveries, read_asset, selection
lazy from ...db.models.asset import Asset
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import CHUNK_SIZE, PAGE_SIZE, Database
lazy from ...domain import (
    ArtBulkSource,
    CollectionPosterStyle,
    MediaSortKey,
    MediaType,
    ServerAsset,
    ThemeBulkSource,
    media_sort_key,
)
lazy from ...jobs.progress_log import JobOutcome, asset_target
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from ...utils.text import count_label
lazy from ...utils.time import utc_now
lazy from ..art.targets import target_label
lazy from ..catalog.index import NO_THEME, THEME_NOT_NEEDED, CatalogIndex, CatalogPick
lazy from ..downloads.queue import JobTarget

type RunParams = BulkMatchArtRequest | BulkThemeRequest
type Source = ArtBulkSource | ThemeBulkSource

#: One planned target of an owner: its asset kind and, for a season poster,
#: the season.
type Slot = tuple[ServerAsset, int | None]

#: Why collection themes need a catalog source.
CATALOG_THEMES_ONLY = "Collection themes require an OvertureDB or ThemerrDB source"


#: Why targets whose saved selection is on disk were not visited.
SAVED_SELECTION = "saved selection already set; Replace existing searches again"

#: What one target came to without being visited: its outcome and the reason.
type PlannedOutcome = tuple[JobOutcome, str]


def planned_outcome(
    params: RunParams,
    *,
    saved: Selection | None,
    selection_missing: bool,
    last_checked: datetime | None,
    catalog: CatalogPick | None,
) -> PlannedOutcome | None:
    """Decide one target from the database, or return ``None`` to visit it.

    This is the planning half of an Assets decision; a visit makes the half
    that needs the files on disk or a source. *saved* is the slot's saved
    selection, and *selection_missing* says the file on disk is not it: the
    file is missing, or was replaced outside Overture. *catalog* is ``None``
    unless the run's sole sources are catalogs, and then is what they offer
    the target.
    The rules apply in order:

    1. A saved selection missing from disk is visited, whenever last
       checked, since the visit downloads the saved choice rather than asking
       a source.
    2. On a catalog-only run, a target no catalog serves is no match, or
       skipped when OvertureDB is disabled: no option would find it anything.
    3. A saved selection on disk that already is the catalog's offer is
       skipped, Overwrite or not: replacing it would fetch the same art.
    4. A saved selection is skipped unless Overwrite is on.
    5. A target checked within the Skip recently checked window is skipped.
    6. Everything else is visited.
    """
    kept = bool(saved) and not params.overwrite_existing
    if kept and selection_missing:
        return None
    if catalog is not None and catalog.value is None:
        outcome = JobOutcome.NO_MATCH if catalog.enabled else JobOutcome.SKIPPED
        return outcome, catalog.reason
    saved_url = saved and (saved.url or saved.youtube_id)
    if catalog is not None and not selection_missing and saved_url == catalog.value:
        return JobOutcome.SKIPPED, f"saved selection is already the {catalog.label}"
    if kept:
        return JobOutcome.SKIPPED, _saved_reason(catalog)
    if checked_recently(last_checked, params):
        return (
            JobOutcome.SKIPPED,
            f"checked within the last {recent_window_label(params)}",
        )
    return None


def _saved_reason(catalog: CatalogPick | None) -> str:
    """Say why a saved selection that is not the catalog's offer is kept."""
    if catalog is None:
        return SAVED_SELECTION
    return (
        f"saved selection differs from the {catalog.label}; "
        "Replace existing would replace it"
    )


def recent_window_label(params: RunParams) -> str:
    """Name the skip-recent window the way the user set it."""
    return count_label(
        params.skip_recent_val, params.skip_recent_unit.value.removesuffix("s")
    )


def checked_recently(last_checked: datetime | None, params: RunParams) -> bool:
    """Return whether *last_checked* falls inside the skip-recent window."""
    if params.skip_recent_val <= 0 or last_checked is None:
        return False
    window = timedelta(seconds=params.skip_recent_val * params.skip_recent_unit.seconds)
    return utc_now() - last_checked < window


@dataclass(frozen=True, slots=True)
class Target:
    """One asset an Assets run decides on."""

    owner: MediaItem | Season | MediaCollection
    kind: ServerAsset
    #: The title a season belongs to; the owner itself for a title.
    item: MediaItem | None = None

    @property
    def collection(self) -> MediaCollection | None:
        """The owner, when it is a collection."""
        return self.owner if isinstance(self.owner, MediaCollection) else None

    @property
    def title(self) -> MediaItem | None:
        """The title the asset belongs to, for a title's or a season's asset."""
        if isinstance(self.owner, MediaItem):
            return self.owner
        return self.item

    @property
    def asset(self) -> Asset:
        return read_asset(self.owner, self.kind)

    @property
    def label(self) -> str:
        """The asset as every log line names it."""
        owner = self.owner
        if isinstance(owner, MediaCollection):
            return asset_target(owner.title, self.kind.value, collection=True)
        title = self.title
        if title is None:
            raise ValueError("A season's asset belongs to its title")
        season = owner if isinstance(owner, Season) else None
        return asset_target(target_label(title, season=season), self.kind.value)

    @property
    def last_checked(self) -> datetime | None:
        """When an Assets run last finished with the asset's owner."""
        return self.owner.last_matched_at

    def job(
        self,
        value: str | None,
        *,
        upload_hash: str | None = None,
        poster_style: CollectionPosterStyle | None = None,
    ) -> JobTarget:
        """The download that makes the asset *value* (a link or video) or the upload.

        Raises:
            ValueError: When a theme names no video, or the title is not stored.
        """
        owner, art_type = self.owner, self.kind.art_type
        if art_type is None and value is None:
            raise ValueError("A theme download names its video")
        if isinstance(owner, MediaCollection):
            if art_type is None:
                return JobTarget.collection_theme(
                    owner.id or 0, owner.title, value or ""
                )
            return JobTarget.collection_art(
                owner.id or 0,
                owner.title,
                art_type,
                value,
                upload_hash=upload_hash,
                poster_style=poster_style,
            )
        title = self.title
        if title is None or title.id is None:
            raise ValueError("A stored title needs its ID to queue downloads")
        if art_type is None:
            return JobTarget.theme(title.id, value or "")
        return JobTarget.art(
            title.id,
            art_type,
            value,
            upload_hash=upload_hash,
            season_id=owner.id if isinstance(owner, Season) else None,
        )


def kinds(params: RunParams) -> list[ServerAsset]:
    """The asset kinds a run decides on, in the order results are listed."""
    if isinstance(params, BulkThemeRequest):
        return [ServerAsset.THEME]
    wanted = {art_type.server_asset for art_type in params.art_types}
    return [kind for kind in ServerAsset if kind in wanted]


@dataclass(frozen=True, slots=True)
class Unusable:
    """A source of the run that cannot serve a target, and why."""

    reason: str


def triage(target: Target, params: RunParams) -> list[Source | Unusable]:
    """The run's sources in order: each that can serve *target*, or why it cannot.

    Local art matching compares a collection's TMDB art with the image in
    place, and YouTube search looks for titles only.
    """
    entries: list[Source | Unusable] = []
    row = target.collection
    for source in params.source_order:
        if row is not None and source is ThemeBulkSource.YOUTUBE_SEARCH:
            continue
        reason = (
            unmatchable(row, target.kind)
            if row is not None and source is ArtBulkSource.LOCAL_ART_MATCHING
            else None
        )
        entries.append(source if reason is None else Unusable(reason))
    if row is not None and target.kind is ServerAsset.THEME and not entries:
        entries.append(Unusable(CATALOG_THEMES_ONLY))
    return entries


def usable(entries: Sequence[Source | Unusable]) -> list[Source]:
    """The sources among *entries* that can serve their target."""
    return [entry for entry in entries if not isinstance(entry, Unusable)]


def unmatchable(row: MediaCollection, kind: ServerAsset) -> str | None:
    """Why local art matching cannot compare a collection's art, if it cannot."""
    if row.tmdb_collection_id is None:
        return "Local art matching: the collection has no TMDB collection ID"
    asset = read_asset(row, kind)
    if asset.content_hash is None and not any(
        seen.observed_ref for seen in asset.deliveries
    ):
        return "Local art matching: the collection has no image to compare"
    return None


def catalog_pick(
    target: Target,
    sources: Sequence[Source],
    index: CatalogIndex,
    *,
    failed: set[str],
) -> CatalogPick:
    """What the catalogs among *sources* offer *target*, or why none does."""
    if target.kind is ServerAsset.THEME:
        owner = target.collection or target.title
        if owner is None:
            raise ValueError("A theme belongs to a title or a collection")
        return index.theme(
            owner,
            [source for source in sources if isinstance(source, ThemeBulkSource)],
            failed=failed,
        )
    art_type = target.kind.art_type
    if art_type is None:
        raise ValueError("Only artwork has an art type")
    if (row := target.collection) is not None:
        return index.collection_art(row, art_type)
    title = target.title
    if title is None:
        raise ValueError("Artwork belongs to a title, a season or a collection")
    season = target.owner if isinstance(target.owner, Season) else None
    return index.art(title, art_type, season=season)


def planning_pick(
    target: Target,
    params: RunParams,
    index: CatalogIndex | None,
    *,
    failed: set[str],
) -> CatalogPick | None:
    """What decides *target* while planning: the catalogs' offer, or nothing.

    ``None`` leaves a target some source other than a catalog can try to its
    visit. A target no usable source can serve is decided as no match.
    """
    entries = triage(target, params)
    sources = usable(entries)
    if not sources:
        reasons = tuple(
            entry.reason for entry in entries if isinstance(entry, Unusable)
        )
        return CatalogPick(None, notes=reasons, enabled=True)
    if index is None or not all(source.catalog for source in sources):
        return None
    pick = catalog_pick(target, sources, index, failed=failed)
    if pick.value is not None:
        return pick
    # Each source's notes stand where it does in the run's order.
    notes: list[str] = []
    for entry in entries:
        if isinstance(entry, Unusable):
            notes.append(entry.reason)
        elif entry is sources[0]:
            notes.extend(pick.notes)
    return CatalogPick(
        None,
        notes=tuple(notes),
        enabled=pick.enabled or len(sources) < len(entries),
    )


def not_needed(target: Target, index: CatalogIndex) -> str | None:
    """Why nothing is needed for *target*, when nothing is.

    What is needed is recorded on the asset; the reason only names its cause.
    """
    if target.asset.needed:
        return None
    row = target.collection
    if row is None:
        return NO_THEME
    if target.kind is not ServerAsset.THEME:
        return f"its collection settings need no {target.kind.value}"
    entry = (
        index.collections.get(row.tmdb_collection_id)
        if row.tmdb_collection_id is not None
        else None
    )
    if entry is None or not entry.no_theme:
        return THEME_NOT_NEEDED
    return NO_THEME


@dataclass(frozen=True, slots=True)
class Batch:
    """A page of planned visits: titles or collections, by ID."""

    collections: bool
    visits: dict[int, tuple[Slot, ...]]


@dataclass(slots=True, frozen=True)
class AssetPlan:
    """Every target of one run: decided while planning, or to visit.

    Visits hold IDs rather than rows, so a plan for the whole library stays
    small; each batch's rows are loaded, and its files read, when visited.
    """

    #: Decided targets by whether they are a collection's, outcome and reason.
    decided: Counter[tuple[bool, JobOutcome, str]] = field(
        default_factory=Counter[tuple[bool, JobOutcome, str]]
    )
    _titles: list[tuple[MediaSortKey, int, tuple[Slot, ...]]] = field(
        default_factory=list[tuple[MediaSortKey, int, tuple[Slot, ...]]]
    )
    _collections: list[tuple[MediaSortKey, int, tuple[Slot, ...]]] = field(
        default_factory=list[tuple[MediaSortKey, int, tuple[Slot, ...]]]
    )

    def decide(self, target: Target, outcome: PlannedOutcome) -> None:
        """Count one target decided while planning."""
        self.decided[(target.collection is not None, *outcome)] += 1

    def visit(self, owner: MediaItem | MediaCollection, slots: list[Slot]) -> None:
        """Keep *owner*'s *slots* for a visit, in the order they are given."""
        if not slots or owner.id is None:
            return
        if isinstance(owner, MediaCollection):
            key = media_sort_key(owner.media_types[0], owner.title, owner.id)
            self._collections.append((key, owner.id, tuple(slots)))
        else:
            key = media_sort_key(owner.media_type, owner.title, owner.id)
            self._titles.append((key, owner.id, tuple(slots)))

    @property
    def total(self) -> int:
        """How many targets the run reports on, decided or visited."""
        visits = (*self._titles, *self._collections)
        return self.decided.total() + sum(len(slots) for _, _, slots in visits)

    def batches(self) -> Iterator[Batch]:
        """Yield the visits a page at a time: titles, then collections, by title."""
        for collections, visits in ((False, self._titles), (True, self._collections)):
            for page in batched(sorted(visits), PAGE_SIZE, strict=False):
                yield Batch(collections, {owner: slots for _, owner, slots in page})


async def _title_chunks(
    params: RunParams, *, database: Database, chunk: int
) -> AsyncGenerator[tuple[AsyncSession, list[MediaItem]]]:
    """Yield the run's titles a chunk at a time, by ID, with their read session."""
    after_id = 0
    while True:
        async with database.read_session() as session:
            items = await MediaItemRepository(session).list_bulk_targets(
                params.library_ids,
                item_ids=params.item_ids,
                include_unmonitored=params.include_unmonitored,
                after_id=after_id,
                limit=chunk,
            )
            yield session, items
        if len(items) < chunk:
            return
        after_id = max(item.id or 0 for item in items)


def title_targets(
    items: Sequence[MediaItem],
    seasons: Sequence[Season],
    wanted: Sequence[ServerAsset],
) -> list[Target]:
    """Every target of *items*: their own assets, then their seasons' posters."""
    by_item: defaultdict[int, list[Season]] = defaultdict(list)
    for season in seasons:
        by_item[season.media_item_id].append(season)
    targets: list[Target] = []
    for item in items:
        targets.extend(
            Target(item, kind)
            for kind in wanted
            if kind is not ServerAsset.SEASON_POSTER
        )
        if ServerAsset.SEASON_POSTER in wanted:
            targets.extend(
                Target(season, ServerAsset.SEASON_POSTER, item)
                for season in by_item[item.id or 0]
            )
    return targets


def collection_targets(
    rows: Sequence[MediaCollection], wanted: Sequence[ServerAsset]
) -> list[Target]:
    """Every target of *rows*: a collection holds no season posters."""
    return [
        Target(row, kind)
        for row in rows
        for kind in wanted
        if kind is not ServerAsset.SEASON_POSTER
    ]


def slot(target: Target) -> Slot:
    return target.kind, target.owner.id if isinstance(target.owner, Season) else None


def _plan_targets(
    plan: AssetPlan,
    targets: list[Target],
    params: RunParams,
    *,
    index: CatalogIndex,
    catalog: bool,
    failed: dict[int, set[str]],
) -> None:
    """Decide what the database alone settles of *targets*; keep the rest."""
    visits: dict[int, tuple[MediaItem | MediaCollection, list[Slot]]] = {}
    for target in targets:
        owner = target.collection or target.title
        if owner is None or owner.id is None:
            continue
        visits.setdefault(owner.id, (owner, []))
        if reason := not_needed(target, index):
            plan.decide(target, (JobOutcome.SKIPPED, reason))
            continue
        asset = target.asset
        decided = planned_outcome(
            params,
            saved=selection(asset),
            selection_missing=bool(missing_deliveries(asset)),
            last_checked=target.last_checked,
            catalog=planning_pick(
                target,
                params,
                index if catalog else None,
                failed=failed.get(owner.id, set[str]()),
            ),
        )
        if decided is None:
            visits[owner.id][1].append(slot(target))
        else:
            plan.decide(target, decided)
    for owner, slots in visits.values():
        plan.visit(owner, slots)


async def plan_run(
    params: RunParams,
    *,
    database: Database,
    chunk: int = CHUNK_SIZE,
) -> AssetPlan:
    """Plan every target in scope without reading a file or asking a source."""
    plan = AssetPlan()
    wanted = kinds(params)
    themes = ServerAsset.THEME in wanted
    # Catalog picks decide a target only when every usable source is a catalog.
    catalog = all(source.catalog for source in params.source_order)
    if not params.collection_scope or params.library_ids:
        async for session, items in _title_chunks(
            params, database=database, chunk=chunk
        ):
            show_ids = [
                item.id
                for item in items
                if item.media_type == MediaType.SHOW and item.id is not None
            ]
            seasons = (
                await SeasonRepository(session).list_tracked_for_items(
                    show_ids, ordered=True
                )
                if ServerAsset.SEASON_POSTER in wanted and show_ids
                else []
            )
            index = (
                await CatalogIndex.build(session, items)
                if catalog
                else CatalogIndex.empty()
            )
            failed = (
                await DownloadJobRepository(session).failed_themes_by_item(
                    [item.id for item in items if item.id is not None]
                )
                if themes and catalog
                else {}
            )
            _plan_targets(
                plan,
                title_targets(items, seasons, wanted),
                params,
                index=index,
                catalog=catalog,
                failed=failed,
            )
    if params.collection_scope:
        after = 0
        while True:
            async with database.read_session() as session:
                rows = await CollectionRepository(session).bulk_targets(
                    after=after,
                    collection_ids=params.collection_ids,
                    collection_groups=params.collection_groups,
                    include_unmonitored=params.include_unmonitored,
                )
                if not rows:
                    break
                index = await CatalogIndex.build_collections(session, rows)
                failed = (
                    await DownloadJobRepository(session).failed_themes_by_collection(
                        [row.id for row in rows if row.id is not None]
                    )
                    if themes
                    else {}
                )
            # A collection's sources are catalogs, unless local art matching
            # can compare its image; planning asks which apply to each.
            _plan_targets(
                plan,
                collection_targets(rows, wanted),
                params,
                index=index,
                catalog=True,
                failed=failed,
            )
            after = rows[-1].id or after
    return plan
