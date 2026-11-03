"""OvertureDB resolution for a batch of media items, done once."""

lazy from collections.abc import Iterable, Mapping, Sequence, Set
lazy from dataclasses import dataclass, field
lazy from typing import Self

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetCollection, PublicDatasetItem
lazy from ...db.models.season import Season
lazy from ...db.models.settings import get_app_settings
lazy from ...domain import ArtType, ThemeBulkSource
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule


def catalog_art_url(
    public_item: PublicDatasetItem,
    season_posters: Mapping[int, str],
    art_type: ArtType,
    season_num: int | None,
) -> str | None:
    """Return the entry's URL for one art slot; *season_posters* by number."""
    if art_type is ArtType.POSTER:
        return public_item.poster_url
    if art_type is ArtType.BACKGROUND:
        return public_item.background_url
    if art_type is ArtType.SEASON_POSTER and season_num is not None:
        return season_posters.get(season_num)
    return None


@dataclass(frozen=True, slots=True)
class CatalogPick:
    """What the catalogs offer one target, or why none of them offers anything.

    The bulk planner and the visit that follows it both read a target's catalog
    answer from here, so a target is decided and explained the same way at
    either stage.
    """

    #: The artwork URL or YouTube ID the catalogs offer, if any.
    value: str | None
    #: What *value* is, as named in a log line ("OvertureDB artwork").
    label: str = ""
    #: Why each catalog asked had nothing, in the order they were asked.
    notes: tuple[str, ...] = ()
    #: False when OvertureDB is disabled, so no catalog was read at all.
    enabled: bool = True

    @property
    def reason(self) -> str:
        """Return why no catalog offers anything, one clause per catalog."""
        return "; ".join(self.notes)


#: Why a theme run leaves a title OvertureDB flags as having no theme.
NO_THEME = "OvertureDB: this title has no theme"

#: Why OvertureDB offers nothing while the user has it switched off.
DATASET_DISABLED = "OvertureDB is disabled"


@dataclass(frozen=True, slots=True)
class PublicDatasetIndex:
    """What OvertureDB holds for a known set of local media items.

    :func:`build` resolves a batch in two queries; each per-target artwork
    lookup then reads this index without further database access.

    An index built while the dataset is disabled is empty, so a caller that
    asks it questions gets the same answer as one that checked the schedule
    first: nothing on offer.
    """

    items: dict[int, PublicDatasetItem]
    season_posters: dict[int, dict[int, str]]
    #: Whether OvertureDB is enabled; a disabled index holds nothing.
    enabled: bool = True
    collections: dict[int, PublicDatasetCollection] = field(
        default_factory=dict[int, PublicDatasetCollection]
    )
    #: Whether the user lets OvertureDB's No theme flag count as a theme.
    trust_no_theme: bool = True

    @classmethod
    async def build_collections(
        cls,
        session: AsyncSession,
        collections: Sequence[MediaCollection],
        *,
        app_config: Settings,
    ) -> Self:
        """Resolve catalog themes for a bounded batch of collections."""
        schedule = await load_schedule(
            session, PUBLIC_DATASET_SCHEDULE, timezone=app_config.TZ
        )
        if not schedule.enabled:
            return cls.empty(enabled=False)
        entries = await PublicDatasetRepository(session).collections_by_tmdb_id(
            {
                row.tmdb_collection_id
                for row in collections
                if row.tmdb_collection_id is not None
            }
        )
        return cls(
            {},
            {},
            collections=entries,
            trust_no_theme=(await get_app_settings(session)).overturedb_no_theme,
        )

    @classmethod
    def empty(cls, *, enabled: bool = True) -> Self:
        """Return an index that holds nothing, for disabled or skipped runs."""
        return cls({}, {}, enabled)

    @classmethod
    async def build(
        cls, session: AsyncSession, items: Sequence[MediaItem], *, app_config: Settings
    ) -> Self:
        """Resolve the dataset's rows for *items*, or nothing when disabled."""
        schedule = await load_schedule(
            session, PUBLIC_DATASET_SCHEDULE, timezone=app_config.TZ
        )
        if not schedule.enabled or not items:
            return cls.empty(enabled=schedule.enabled)

        repository = PublicDatasetRepository(session)
        matched = await repository.items_by_media_item_id(items)
        season_posters = await repository.season_posters_by_item_ids(
            {
                public_item.id
                for public_item in matched.values()
                if public_item.id is not None
            }
        )
        return cls(
            matched,
            season_posters,
            trust_no_theme=(await get_app_settings(session)).overturedb_no_theme,
        )

    def art_url(
        self,
        item: MediaItem,
        art_type: ArtType,
        *,
        season: Season | None = None,
    ) -> str | None:
        """Return the dataset's URL for one art slot, if it has one."""
        public_item = self.items.get(item.id) if item.id is not None else None
        if public_item is None or public_item.id is None:
            return None
        return catalog_art_url(
            public_item,
            self.season_posters.get(public_item.id, {}),
            art_type,
            season.season_num if season else None,
        )

    def art(
        self, item: MediaItem, art_type: ArtType, *, season: Season | None = None
    ) -> CatalogPick:
        """Return OvertureDB's artwork for one slot, or why it has none."""
        if url := self.art_url(item, art_type, season=season):
            return CatalogPick(url, "OvertureDB artwork")
        return CatalogPick(
            None,
            notes=(self._missing(item, f"no {art_type.label} for it"),),
            enabled=self.enabled,
        )

    def has_no_theme(self, item: MediaItem | MediaCollection) -> bool:
        """Whether OvertureDB says *item* has no theme music."""
        public_item = (
            self.collections.get(item.tmdb_collection_id or 0)
            if isinstance(item, MediaCollection)
            else self.items.get(item.id or 0)
        )
        return (
            self.enabled
            and self.trust_no_theme
            and public_item is not None
            and public_item.no_theme
        )

    def theme(
        self,
        item: MediaItem | MediaCollection,
        sources: Iterable[ThemeBulkSource],
        *,
        failed: Set[str] = frozenset(),
    ) -> CatalogPick:
        """Return the first theme a catalog in *sources* offers, or why none does.

        A theme in *failed* failed to download for *item* before, so it is
        passed over. Sources that are not catalogs are not asked.
        """
        public_item = (
            self.collections.get(item.tmdb_collection_id or 0)
            if isinstance(item, MediaCollection)
            else self.items.get(item.id or 0)
        )
        notes: list[str] = []
        for source in sources:
            if not source.catalog:
                continue
            youtube_id = public_item and _catalog_youtube_id(public_item, source)
            if not youtube_id:
                notes.append(self._theme_missing(item, source))
            elif youtube_id in failed:
                notes.append(f"the {source.label} theme failed to download before")
            else:
                return CatalogPick(youtube_id, f"{source.label} theme")
        if not notes and isinstance(item, MediaCollection):
            notes.append("Collection themes require an OvertureDB or ThemerrDB source")
        return CatalogPick(None, notes=tuple(notes), enabled=self.enabled)

    def _missing(self, item: MediaItem | MediaCollection, what: str) -> str:
        """Say why OvertureDB has nothing: disabled, no entry, or *what*."""
        if not self.enabled:
            return DATASET_DISABLED
        if (
            isinstance(item, MediaCollection)
            and item.tmdb_collection_id not in self.collections
        ) or (isinstance(item, MediaItem) and item.id not in self.items):
            return "OvertureDB has no entry for it"
        return f"OvertureDB has {what}"

    def _theme_missing(
        self, item: MediaItem | MediaCollection, source: ThemeBulkSource
    ) -> str:
        """Say why one catalog has no theme for *item*.

        ThemerrDB's themes arrive with OvertureDB's catalog, so both depend on
        OvertureDB being enabled; only OvertureDB's own entries are its
        "entries", since a ThemerrDB theme may come without one.
        """
        if source is ThemeBulkSource.OVERTUREDB:
            return self._missing(item, "no theme for it")
        if not self.enabled:
            return "ThemerrDB needs OvertureDB enabled"
        return "ThemerrDB has no theme for it"


def _catalog_youtube_id(
    public_item: PublicDatasetItem | PublicDatasetCollection, source: ThemeBulkSource
) -> str | None:
    """Return one catalog's theme video ID for an entry."""
    match source:
        case ThemeBulkSource.OVERTUREDB:
            return public_item.youtube_id_overturedb
        case ThemeBulkSource.THEMERRDB:
            return public_item.youtube_id_themerrdb
        case ThemeBulkSource.YOUTUBE_SEARCH:
            return None
