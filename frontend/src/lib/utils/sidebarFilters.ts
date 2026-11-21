import type {
  CatalogSelections,
  CollectionRead,
  MediaItemRead,
  MetadataIssue,
  ThemeIdSource,
  TitleAssets,
} from "../../generated/rest/types.gen";
import { METADATA_ISSUES, SELECTED_ART_SOURCE_LABELS } from "../../generated/settings";
import type { FilterState } from "../stores/uiState.svelte";
import { alphabetical } from "./alphabetical";
import { CATALOG_SELECTION_FILTERS, type CatalogSelectionFilter } from "./catalogSelections";
import { keysOf } from "./records";
import {
  inRange,
  isRangeActive,
  matchesTriState,
  type ArtSource,
  type CatalogPresence,
  type Predicate,
  type Row,
  type SidebarMode,
  type SidebarSource,
  type SidebarTab,
} from "./sidebarShared";

export const CATALOG_FILTER_LABELS = {
  poster: "Poster",
  background: "Background",
  seasonPosters: "Season posters",
  overturedb: "OvertureDB theme",
  themerrdb: "ThemerrDB theme",
  draft: "Has draft",
  library: "In library",
} as const;
export const CATALOG_FILTER_KEYS = keysOf(CATALOG_FILTER_LABELS);
export type CatalogFilters = Record<keyof typeof CATALOG_FILTER_LABELS, CatalogPresence>;

/** How many catalog filters narrow the list; season posters only narrow shows. */
export function catalogFilterCount(filters: CatalogFilters, tab: SidebarTab): number {
  return CATALOG_FILTER_KEYS.filter(
    (key) => (key !== "seasonPosters" || tab === "show") && filters[key] !== "all",
  ).length;
}

export function defaultCatalogFilters(): CatalogFilters {
  return {
    poster: "all",
    background: "all",
    seasonPosters: "all",
    overturedb: "all",
    themerrdb: "all",
    draft: "all",
    library: "all",
  };
}

export const TMDB_FILTER_LABELS = {
  library: "In library",
  overturedb: "In OvertureDB",
} as const;
export type TmdbFilterKey = keyof typeof TMDB_FILTER_LABELS;
export type TmdbFilters = Record<TmdbFilterKey, CatalogPresence>;

export function defaultTmdbFilters(): TmdbFilters {
  return { library: "all", overturedb: "all" };
}

/**
 * The filters TMDB results offer. A title or collection the list does not hold
 * has none of its statuses, so only where it is held can be asked; a TMDB
 * collection is looked up only in the list it is searched from.
 */
export function tmdbFilterKeys(
  source: SidebarSource,
  mode: SidebarMode,
  catalogEnabled: boolean,
): TmdbFilterKey[] {
  if (mode === "collections") return [source];
  return catalogEnabled ? ["library", "overturedb"] : ["library"];
}

/** Where an item's theme ID came from; the file sources are read from its tags. */
export const THEME_SOURCE_LABELS: Record<ThemeIdSource, string> = {
  download: "Downloaded",
  embedded_id: "File ID tag",
  source_url: "File source link",
  metadata_url: "Other file link",
  selection: "Selected",
};
export const THEME_SOURCES = alphabetical(
  keysOf(THEME_SOURCE_LABELS),
  (source) => THEME_SOURCE_LABELS[source],
);

/** Where an item's selected artwork comes from; OvertureDB's catalog art counts as its own. */
export const ART_SOURCE_LABELS: Record<ArtSource, string> = SELECTED_ART_SOURCE_LABELS;
export const ART_SOURCES = alphabetical(
  keysOf(ART_SOURCE_LABELS),
  (source) => ART_SOURCE_LABELS[source],
);

/** Which of a row's artwork the art source filter looks at. */
export const ART_SOURCE_SLOTS = {
  any: ["poster", "background"],
  poster: ["poster"],
  background: ["background"],
} as const satisfies Record<string, readonly (keyof TitleAssets)[]>;
export type ArtSourceSlot = keyof typeof ART_SOURCE_SLOTS;

export type { MetadataIssue };
/** Every metadata issue, by its label. */
export const METADATA_ISSUE_FLAGS = alphabetical(
  keysOf(METADATA_ISSUES),
  (flag) => METADATA_ISSUES[flag].label,
);

/** Whether *flag* can be checked in the list: OvertureDB's issues need it enabled. */
function issueAvailable(
  flag: MetadataIssue,
  catalogEnabled: boolean,
  mode: SidebarMode = "items",
): boolean {
  const issue = METADATA_ISSUES[flag];
  return (catalogEnabled || !issue.needsCatalog) && (mode === "items" || issue.collections);
}

export function metadataIssuesFor(
  tab: SidebarTab,
  catalogEnabled: boolean,
  mode: SidebarMode = "items",
): MetadataIssue[] {
  return METADATA_ISSUE_FLAGS.filter(
    (flag) =>
      (tab === "show" || !METADATA_ISSUES[flag].showOnly) &&
      issueAvailable(flag, catalogEnabled, mode),
  );
}

/**
 * Where the filters popup places a filter, in order. A titled group shares one
 * section; each filter of an untitled group gets a section of its own.
 */
export const FILTER_GROUPS = {
  libraries: null,
  status: "Status",
  art: "Art",
  theme: "Theme music",
  collection: null,
  metadata: null,
} as const;
export type FilterGroup = keyof typeof FILTER_GROUPS;

/**
 * One filter: its heading, its place, and the predicate it adds for each list
 * it applies to, or ``null`` while it is left at All.
 */
interface FilterDef {
  label: string;
  group: FilterGroup;
  order: number;
  mediaTypes?: readonly SidebarTab[];
  /** Shown only while OvertureDB is enabled. */
  needsCatalog?: boolean;
  /** Shown only where the server has smart collections. */
  needsSmart?: boolean;
  /** Shown only where the server has collections. */
  needsCollections?: boolean;
  library?: (
    filters: FilterState,
    catalogEnabled: boolean,
    members: ReadonlySet<number>,
  ) => Predicate<MediaItemRead> | null;
  collections?: (filters: FilterState, catalogEnabled: boolean) => Predicate<CollectionRead> | null;
}

function triState<T>(
  filter: string,
  whenTrue: string,
  value: (row: T) => boolean,
): Predicate<T> | null {
  return filter === "all" ? null : (row) => matchesTriState(value(row), filter, whenTrue);
}

function artSourcePredicate(filters: FilterState): Predicate<Row> | null {
  if (!filters.artSource.sources.length) return null;
  const sources = new Set<string | null>(filters.artSource.sources);
  const slots = ART_SOURCE_SLOTS[filters.artSource.artType];
  return (row) => slots.some((slot) => sources.has(row.assets[slot].source));
}

function resolutionPredicate(filters: FilterState): Predicate<Row> | null {
  if (!isRangeActive(filters.resolution)) return null;
  const slot = filters.resolution.artType;
  return (row) => inRange(row.assets[slot].width, filters.resolution);
}

function issuesPredicate(
  filters: FilterState,
  catalogEnabled: boolean,
  mode: SidebarMode,
): Predicate<{ metadata_issues: MetadataIssue[] }> | null {
  const flags = filters.metadataIssues.flags.filter((flag) =>
    issueAvailable(flag, catalogEnabled, mode),
  );
  if (!flags.length) return null;
  const has = (row: { metadata_issues: MetadataIssue[] }, flag: MetadataIssue) =>
    row.metadata_issues.includes(flag);
  return filters.metadataIssues.mode === "any"
    ? (row) => flags.some((flag) => has(row, flag))
    : (row) => flags.every((flag) => has(row, flag));
}

/**
 * A filter on how one slot's selection compares with OvertureDB's. A title
 * without a catalog entry has nothing to compare, so it never matches one.
 */
function selectionFilter(
  key: CatalogSelectionFilter,
  label: string,
  group: FilterGroup,
  order: number,
): FilterDef {
  const slot = CATALOG_SELECTION_FILTERS[key];
  const predicate = (filters: FilterState, catalogEnabled: boolean) => {
    const wanted = filters[key];
    return catalogEnabled && wanted !== "all"
      ? (row: { catalog_selections: CatalogSelections | null }) =>
          row.catalog_selections?.[slot] === wanted
      : null;
  };
  return { label, group, order, needsCatalog: true, library: predicate, collections: predicate };
}

/**
 * Every filter section, placed by ``order``, which follows ``FILTER_GROUPS``.
 * Within a group the most used come first, and filters offering the same
 * choices sit together.
 */
export const FILTERS = {
  libraries: {
    label: "Libraries",
    group: "libraries",
    order: 10,
    library: (filters) =>
      filters.libraryIds.length
        ? (item) => item.copies.some((copy) => filters.libraryIds.includes(copy.library_id))
        : null,
    collections: (filters) =>
      filters.libraryIds.length
        ? (row) => row.library_ids.some((id) => filters.libraryIds.includes(id))
        : null,
  },
  collection: {
    label: "Collection",
    group: "collection",
    order: 350,
    needsCollections: true,
    library: (filters, _catalogEnabled, members) =>
      filters.collectionId === null ? null : (item) => members.has(item.id),
  },
  collectionHolds: {
    label: "Holds",
    group: "status",
    order: 130,
    collections: (filters) => {
      const { collectionHolds: holds } = filters;
      if (holds === "all") return null;
      return (row) =>
        holds === "both" ? row.media_types.length > 1 : row.media_types.join() === holds;
    },
  },
  collectionOrigin: {
    label: "Made as",
    group: "status",
    order: 125,
    collections: (filters) =>
      triState(filters.collectionOrigin, "set", (row) => row.generated_value !== null),
  },
  monitored: {
    label: "Monitor status",
    group: "status",
    order: 20,
    library: (filters) => triState(filters.monitored, "monitored", (item) => item.monitored),
    collections: (filters) => triState(filters.monitored, "monitored", (row) => row.monitored),
  },
  art: {
    label: "Art complete",
    group: "status",
    order: 30,
    library: (filters) =>
      triState(filters.art, "complete", (item) => item.art_status === "complete"),
    collections: (filters) =>
      triState(filters.art, "complete", (row) => row.art_status === "complete"),
  },
  aspectRatio: {
    label: "Aspect ratio",
    group: "status",
    order: 70,
    library: (filters) =>
      triState(filters.aspectRatio, "incorrect", (item) => item.has_incorrect_aspect_ratio),
    collections: (filters) =>
      triState(filters.aspectRatio, "incorrect", (row) => row.has_incorrect_aspect_ratio),
  },
  resolution: {
    label: "Art resolution",
    group: "art",
    order: 200,
    library: resolutionPredicate,
    collections: resolutionPredicate,
  },
  artSource: {
    label: "Art source",
    group: "art",
    order: 210,
    library: artSourcePredicate,
    collections: artSourcePredicate,
  },
  theme: {
    label: "Theme complete",
    group: "status",
    order: 40,
    library: (filters) =>
      triState(filters.theme, "complete", (item) => item.assets.theme.status === "complete"),
    collections: (filters) =>
      triState(filters.theme, "complete", (row) => row.assets.theme.status === "complete"),
  },
  themeLength: {
    label: "Theme length",
    group: "theme",
    order: 300,
    library: (filters) =>
      isRangeActive(filters.themeLength)
        ? (item) => inRange(item.assets.theme.duration, filters.themeLength)
        : null,
    collections: (filters) =>
      isRangeActive(filters.themeLength)
        ? (row) => inRange(row.assets.theme.duration, filters.themeLength)
        : null,
  },
  themeSources: {
    label: "Theme source",
    group: "theme",
    order: 310,
    library: (filters) => {
      if (!filters.themeSources.length) return null;
      const sources = new Set(filters.themeSources);
      return (item) => {
        const source = item.assets.theme.youtube_id_source;
        return !!source && sources.has(source);
      };
    },
  },
  overtureDb: {
    label: "OvertureDB",
    group: "status",
    order: 50,
    needsCatalog: true,
    library: (filters, catalogEnabled) =>
      catalogEnabled
        ? triState(filters.overtureDb, "complete", (item) => item.catalog_complete)
        : null,
    collections: (filters, catalogEnabled) =>
      catalogEnabled
        ? triState(filters.overtureDb, "complete", (row) => row.catalog_complete)
        : null,
  },
  themerrDb: {
    label: "ThemerrDB",
    group: "status",
    order: 60,
    needsCatalog: true,
    library: (filters, catalogEnabled) =>
      catalogEnabled
        ? triState(filters.themerrDb, "complete", (item) => item.catalog_themerrdb)
        : null,
    collections: (filters, catalogEnabled) =>
      catalogEnabled
        ? triState(filters.themerrDb, "complete", (row) => row.catalog_themerrdb)
        : null,
  },
  catalogPoster: selectionFilter("catalogPoster", "OvertureDB poster", "art", 220),
  catalogBackground: selectionFilter("catalogBackground", "OvertureDB background", "art", 230),
  catalogSeasonPosters: {
    ...selectionFilter("catalogSeasonPosters", "OvertureDB season posters", "art", 240),
    mediaTypes: ["show"],
  },
  catalogTheme: selectionFilter("catalogTheme", "OvertureDB theme", "theme", 320),
  metadataIssues: {
    label: "Metadata issues",
    group: "metadata",
    order: 400,
    library: (filters, catalogEnabled) => issuesPredicate(filters, catalogEnabled, "items"),
    collections: (filters, catalogEnabled) =>
      issuesPredicate(filters, catalogEnabled, "collections"),
  },
  collectionMembers: {
    label: "Management",
    group: "status",
    order: 110,
    collections: (filters) => triState(filters.collectionMembers, "managed", (row) => row.managed),
  },
  collectionKind: {
    label: "Kind",
    group: "status",
    order: 120,
    needsSmart: true,
    collections: (filters) =>
      triState(filters.collectionKind, "smart", (row) => row.kind === "smart"),
  },
  collectionSync: {
    label: "Last sync",
    group: "status",
    order: 90,
    // Only collections with criteria sync.
    collections: (filters) =>
      filters.collectionSync === "all"
        ? null
        : (row) =>
            row.managed && matchesTriState(row.sync_failed, filters.collectionSync, "failed"),
  },
  collectionSize: {
    label: "Size",
    group: "status",
    order: 100,
    collections: (filters) =>
      filters.collectionSize === "empty"
        ? (row) => row.child_count === 0
        : filters.collectionSize === "below_minimum"
          ? (row) => row.below_minimum
          : null,
  },
  mediaServer: {
    label: "Media server",
    group: "status",
    order: 80,
    // Items the server removed are not listed, so only unlinked ones are missing.
    library: (filters) => triState(filters.mediaServer, "missing", (item) => !item.copies.length),
    collections: (filters) => triState(filters.mediaServer, "missing", (row) => row.withheld),
  },
} as const satisfies Record<string, FilterDef>;
export type FilterKey = keyof typeof FILTERS;

/** The filter sections a list shows, in order. */
export function filterSections(
  mode: SidebarMode,
  options: { tab: SidebarTab; catalogEnabled: boolean; smart: boolean; collections: boolean },
): FilterKey[] {
  const scope = mode === "collections" ? "collections" : "library";
  return keysOf(FILTERS)
    .filter((key) => {
      const filter: FilterDef = FILTERS[key];
      return (
        !!filter[scope] &&
        (!filter.mediaTypes || filter.mediaTypes.includes(options.tab)) &&
        (!filter.needsCatalog || options.catalogEnabled) &&
        (!filter.needsSmart || options.smart) &&
        (!filter.needsCollections || options.collections)
      );
    })
    .sort((a, b) => FILTERS[a].order - FILTERS[b].order);
}

export function libraryPredicates(
  filters: FilterState,
  catalogEnabled: boolean,
  members: ReadonlySet<number> = new Set(),
): Predicate<MediaItemRead>[] {
  return keysOf(FILTERS).flatMap((key) => {
    const filter: FilterDef = FILTERS[key];
    return filter.library?.(filters, catalogEnabled, members) ?? [];
  });
}

export function collectionPredicates(
  filters: FilterState,
  catalogEnabled: boolean,
): Predicate<CollectionRead>[] {
  return keysOf(FILTERS).flatMap((key) => {
    const filter: FilterDef = FILTERS[key];
    return filter.collections?.(filters, catalogEnabled) ?? [];
  });
}

/** How many of the list's filters narrow it now. */
export function activeFilterCount(
  filters: FilterState,
  catalogEnabled: boolean,
  mode: SidebarMode,
): number {
  return mode === "collections"
    ? collectionPredicates(filters, catalogEnabled).length
    : libraryPredicates(filters, catalogEnabled).length + (filters.customFilter === null ? 0 : 1);
}

/** *filters* with every filter that reads OvertureDB back at its *defaults*. */
export function withoutCatalogFilters(filters: FilterState, defaults: FilterState): FilterState {
  const reset = { ...filters };
  for (const key of keysOf(FILTERS)) {
    const def: FilterDef = FILTERS[key];
    if (def.needsCatalog && key in defaults) {
      Object.assign(reset, { [key]: defaults[key as keyof FilterState] });
    }
  }
  return reset;
}
