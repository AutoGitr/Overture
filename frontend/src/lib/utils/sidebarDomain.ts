import {
  ASPECT_RATIOS,
  SELECTED_ART_SOURCE_LABELS,
  UNMANAGED_GROUP,
} from "../../generated/settings";
import type {
  CatalogEntryRow,
  CollectionRead,
  MediaItemRead,
} from "../../generated/rest/types.gen";
import type { FilterState, NumberRange } from "../stores/uiState.svelte";
import { extractYouTubeId } from "./themeSearch";
import { keysOf } from "./records";

export type SidebarTab = "movie" | "show";
export type SidebarMode = "items" | "collections";
export type SidebarSource = "library" | "overturedb";
export type CatalogPresence = "all" | "present" | "missing";
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

export function filterCatalogEntries(options: {
  entries: CatalogEntryRow[];
  filters: CatalogFilters;
  searchQuery: string;
  searchField?: SidebarSearchField;
  sortField?: SidebarSortField;
  sortDir?: SidebarSortDir;
}): CatalogEntryRow[] {
  const { filters } = options;
  const rows = options.entries.filter((entry) => {
    const presence: Record<keyof CatalogFilters, boolean> = {
      poster: !!entry.poster_url,
      background: !!entry.background_url,
      seasonPosters: entry.season_posters > 0,
      overturedb: !!entry.youtube_id_overturedb,
      themerrdb: !!entry.youtube_id_themerrdb,
      draft: entry.has_draft,
      library: entry.library_item_id !== null || entry.library_collection_id !== null,
    };
    return keysOf(filters).every(
      (key) =>
        (key === "seasonPosters" && entry.media_type !== "show") ||
        matchesTriState(presence[key], filters[key], "present"),
    );
  });
  const query = options.searchQuery.trim();
  const matcher = query ? search(options.searchField ?? "title")?.overturedb : undefined;
  const matching = matcher ? rows.filter(matcher(query)) : rows;
  return sortBy(matching, "overturedb", options.sortField, options.sortDir);
}
export type SidebarSortDir = "asc" | "desc";
export type StatusTone = "success" | "warning" | "danger" | "downloading";

/** Catalog badges describe the selections the entry currently holds. */
export function catalogStatus(entry: {
  media_type: CatalogEntryRow["media_type"];
  poster_url: string | null;
  background_url: string | null;
  youtube_id_overturedb: string | null;
  youtube_id_themerrdb: string | null;
  seasons?: { season_num: number; poster_url: string | null }[] | null;
  season_posters?: number;
}): Record<"poster" | "background" | "seasons" | "art" | "theme", StatusTone> {
  const poster = !!entry.poster_url;
  const background = !!entry.background_url;
  const seasons = entry.seasons?.some((season) => !!season.poster_url) ?? !!entry.season_posters;
  const artwork = [poster, background, ...(entry.media_type === "show" ? [seasons] : [])];
  return {
    poster: poster ? "success" : "danger",
    background: background ? "success" : "danger",
    seasons: seasons ? "success" : "danger",
    art: artwork.every(Boolean) ? "success" : artwork.some(Boolean) ? "warning" : "danger",
    theme: entry.youtube_id_overturedb || entry.youtube_id_themerrdb ? "success" : "danger",
  };
}
export type ThemeSource = NonNullable<MediaItemRead["youtube_id_source"]>;
/** The hosts a selected artwork is attributed to. */
export type ArtSource = keyof typeof SELECTED_ART_SOURCE_LABELS;
export type AssetStatus = MediaItemRead["art_status"];

const titleCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function timestamp(value: string | null): number | null {
  return value ? Date.parse(value) : null;
}

/** Which list a sort, search or filter applies to; each list remembers its own sort. */
export type SortScope = "library" | "collections" | "overturedb";

type SortKey = number | string | null;

/** One sort, by the list it applies to: the row's key, where rows without one stay last. */
interface SortDef {
  label: string;
  shortLabel: string;
  library?: (row: MediaItemRead) => SortKey;
  collections?: (row: CollectionRead) => SortKey;
  overturedb?: (row: CatalogEntryRow) => SortKey;
}

/** How far art is from its slot's shape, |w/h - target| / target; unmeasured art has none. */
export function aspectDeviation(
  width: number | null,
  height: number | null,
  artType: keyof typeof ASPECT_RATIOS,
): number | null {
  if (!width || !height) return null;
  const target = ASPECT_RATIOS[artType];
  return Math.abs(width / height - target) / target;
}

/** The art and theme fields a catalog entry has filled. */
function catalogCompleteness(entry: CatalogEntryRow): number {
  return [
    entry.poster_url,
    entry.background_url,
    entry.media_type === "show" ? entry.season_posters > 0 : null,
    entry.youtube_id_overturedb,
    entry.youtube_id_themerrdb,
  ].filter(Boolean).length;
}

/** Every sort, in menu order. */
export const SORTS = {
  title: {
    label: "Title",
    shortLabel: "Title",
    library: (item) => item.title,
    collections: (collection) => collection.title,
    overturedb: (entry) => entry.title,
  },
  sort_title: {
    label: "Sort title (media server order)",
    shortLabel: "Sort title",
    collections: (collection) => collection.sort_title || collection.title,
  },
  year: {
    label: "Year",
    shortLabel: "Year",
    library: (item) => item.year,
    overturedb: (entry) => entry.year,
  },
  group: {
    label: "Group",
    shortLabel: "Group",
    collections: (collection) => collection.collection_group,
  },
  home_order: {
    label: "Home order",
    shortLabel: "Home",
    collections: (collection) => collection.home_order,
  },
  child_count: {
    label: "Number of items",
    shortLabel: "Items",
    collections: (collection) => collection.child_count,
  },
  server_added_at: {
    label: "Date added",
    shortLabel: "Added",
    library: (item) => timestamp(item.server_added_at),
    collections: (collection) => timestamp(collection.server_added_at),
  },
  last_synced_at: {
    label: "Last synced",
    shortLabel: "Synced",
    library: (item) => timestamp(item.last_synced_at),
    collections: (collection) => timestamp(collection.last_rule_sync),
  },
  last_matched_at: {
    label: "Last matched",
    shortLabel: "Matched",
    library: (item) => timestamp(item.last_matched_at),
  },
  poster_resolution: {
    label: "Poster width",
    shortLabel: "Poster",
    library: (item) => item.poster_width,
    collections: (collection) => collection.poster_width,
  },
  background_resolution: {
    label: "Background width",
    shortLabel: "Background",
    library: (item) => item.background_width,
    collections: (collection) => collection.background_width,
  },
  poster_aspect: {
    label: "Poster aspect deviation",
    shortLabel: "Poster shape",
    library: (item) => aspectDeviation(item.poster_width, item.poster_height, "poster"),
    collections: (row) => aspectDeviation(row.poster_width, row.poster_height, "poster"),
  },
  background_aspect: {
    label: "Background aspect deviation",
    shortLabel: "Background shape",
    library: (item) => aspectDeviation(item.background_width, item.background_height, "background"),
    collections: (row) =>
      aspectDeviation(row.background_width, row.background_height, "background"),
  },
  theme_length: {
    label: "Theme length",
    shortLabel: "Theme",
    library: (item) => item.theme_duration,
    collections: (collection) => collection.theme_duration,
  },
  completeness: {
    label: "Completeness",
    shortLabel: "Complete",
    overturedb: catalogCompleteness,
  },
  has_draft: {
    label: "Has draft",
    shortLabel: "Draft",
    overturedb: (entry) => (entry.has_draft ? 1 : 0),
  },
  in_library: {
    label: "In library",
    shortLabel: "Library",
    overturedb: (entry) =>
      entry.library_item_id !== null || entry.library_collection_id !== null ? 1 : 0,
  },
} as const satisfies Record<string, SortDef>;
export type SidebarSortField = keyof typeof SORTS;

export interface MenuEntry<F extends string> {
  id: F;
  label: string;
  shortLabel: string;
}

function sortKey(field: string, scope: SortScope): ((row: never) => SortKey) | undefined {
  const sort: SortDef | undefined = hasKey(SORTS, field) ? SORTS[field] : undefined;
  return sort?.[scope];
}

/** The sort fields a list offers, in menu order. */
export function sortMenu(scope: SortScope): MenuEntry<SidebarSortField>[] {
  return keysOf(SORTS)
    .filter((id) => sortKey(id, scope))
    .map((id) => ({ id, label: SORTS[id].label, shortLabel: SORTS[id].shortLabel }));
}

export type SidebarSortPreference = { field: SidebarSortField; dir: SidebarSortDir };

const ASCENDING_SORTS: ReadonlySet<SidebarSortField> = new Set([
  "title",
  "sort_title",
  "group",
  "home_order",
]);

/** Names and orders read A to Z; measures, dates and deviations worst or newest first. */
export function defaultSortDir(field: SidebarSortField): SidebarSortDir {
  return ASCENDING_SORTS.has(field) ? "asc" : "desc";
}

export function normalizeSortPreference(value: unknown, scope: SortScope): SidebarSortPreference {
  const stored = value && typeof value === "object" ? value : {};
  const field = "field" in stored ? stored.field : undefined;
  const dir = "dir" in stored ? stored.dir : undefined;
  return {
    field: sortMenu(scope).find((entry) => entry.id === field)?.id ?? "title",
    dir: dir === "desc" ? "desc" : "asc",
  };
}

/**
 * Sorts by the key in place. Rows without a value stay last in either
 * direction, and ties fall back to ascending title.
 */
function sortRows<T extends { title: string }>(
  rows: T[],
  key: (row: T) => SortKey,
  dir: SidebarSortDir,
): T[] {
  const direction = dir === "asc" ? 1 : -1;
  return rows
    .map((row) => ({ row, key: key(row) }))
    .sort((a, b) => {
      if (a.key !== b.key) {
        if (a.key === null) return 1;
        if (b.key === null) return -1;
        const order =
          typeof a.key === "string" || typeof b.key === "string"
            ? titleCollator.compare(String(a.key), String(b.key))
            : a.key - b.key;
        if (order) return order * direction;
      }
      return titleCollator.compare(a.row.title, b.row.title);
    })
    .map(({ row }) => row);
}

function sortBy<T extends { title: string }>(
  rows: T[],
  scope: SortScope,
  field: string | undefined,
  dir: SidebarSortDir | undefined,
): T[] {
  // A list's own sorts take its row type; an unknown field sorts by title.
  const key = (sortKey(field ?? "title", scope) ?? sortKey("title", scope)) as (row: T) => SortKey;
  return sortRows(rows, key, dir ?? "asc");
}

type Matcher<T> = (query: string) => (row: T) => boolean;

/** One search-by field, by the list it applies to; a list without a matcher lacks it. */
interface SearchDef {
  label: string;
  /** What the field is called in the collection list, where it differs. */
  collectionsLabel?: string;
  placeholder?: string;
  movieOnly?: boolean;
  library?: Matcher<MediaItemRead>;
  collections?: Matcher<CollectionRead>;
  overturedb?: Matcher<CatalogEntryRow>;
  /** Searches TMDB on the server instead of filtering the library. */
  tmdb?: true;
}

function textMatcher<T>(text: (row: T) => string | null): Matcher<T> {
  return (query) => {
    const needle = query.toLowerCase();
    return (row) => text(row)?.toLowerCase().includes(needle) ?? false;
  };
}

function youtubeMatcher<T>(
  ids: (row: T) => (string | null)[],
  title: (row: T) => string | null,
): Matcher<T> {
  return (query) => {
    const linkedId = extractYouTubeId(query);
    const needle = query.toLowerCase();
    return (row) =>
      linkedId
        ? ids(row).includes(linkedId)
        : ids(row).some((id) => id?.toLowerCase() === needle) ||
          (title(row)?.toLowerCase().includes(needle) ?? false);
  };
}

function externalIdMatcher<
  T extends { tmdb_id: number | null; tvdb_id: number | null; imdb_id: string | null },
>(): Matcher<T> {
  return (query) => {
    // A pasted IMDb link carries its ID; every other ID must match exactly.
    const id = (/tt\d+/i.exec(query)?.[0] ?? query).toLowerCase();
    return (row) =>
      [row.tmdb_id, row.tvdb_id, row.imdb_id].some(
        (value) => value != null && String(value).toLowerCase() === id,
      );
  };
}

/** Every search-by field, in menu order. */
export const SEARCHES = {
  title: {
    label: "Title",
    collectionsLabel: "Title or TMDB collection ID",
    library: textMatcher((item) => item.title),
    collections: (query) => {
      const byTitle = textMatcher<CollectionRead>((collection) => collection.title)(query);
      return (collection) =>
        String(collection.tmdb_collection_id ?? "") === query || byTitle(collection);
    },
    overturedb: textMatcher((entry) => entry.title),
  },
  director: {
    label: "Director",
    placeholder: "Search directors...",
    movieOnly: true,
    library: textMatcher((item) => (item.media_type === "movie" ? item.director : null)),
  },
  studio: {
    label: "Studio",
    placeholder: "Search studios...",
    library: textMatcher((item) => item.studio),
  },
  group: {
    label: "Group",
    placeholder: "Search groups...",
    collections: textMatcher((collection) => collection.collection_group),
  },
  year: {
    label: "Year",
    placeholder: "Search years...",
    library: (query) => (item) => String(item.year ?? "").startsWith(query),
    overturedb: (query) => (entry) => String(entry.year ?? "").startsWith(query),
  },
  external_id: {
    label: "TMDB, TVDB or IMDb ID",
    placeholder: "Search IDs...",
    library: externalIdMatcher(),
    overturedb: externalIdMatcher(),
  },
  youtube: {
    label: "YouTube link, ID or title",
    placeholder: "Search YouTube...",
    library: youtubeMatcher(
      (item) => [item.youtube_id],
      (item) => item.youtube_title,
    ),
    collections: youtubeMatcher(
      (collection) => [collection.youtube_id],
      (collection) => collection.youtube_title,
    ),
    overturedb: youtubeMatcher(
      (entry) => [entry.youtube_id_overturedb, entry.youtube_id_themerrdb],
      () => null,
    ),
  },
  tmdb: {
    // Listed under a "TMDB" heading, apart from the library fields.
    label: "Title or ID",
    placeholder: "Search TMDB by title or ID...",
    tmdb: true,
  },
} as const satisfies Record<string, SearchDef>;
export type SidebarSearchField = keyof typeof SEARCHES;

function search(field: string): SearchDef | undefined {
  return hasKey(SEARCHES, field) ? SEARCHES[field] : undefined;
}

export interface SearchFieldGroup {
  label: "Library" | "TMDB" | "OvertureDB" | "Collections";
  fields: MenuEntry<SidebarSearchField>[];
}

function searchEntries(
  fields: readonly SidebarSearchField[],
  scope: SortScope,
): MenuEntry<SidebarSearchField>[] {
  return fields.map((id) => {
    const field: SearchDef = SEARCHES[id];
    const label = (scope === "collections" && field.collectionsLabel) || field.label;
    return { id, label, shortLabel: label };
  });
}

/** The search fields a list offers; library fields first, then TMDB's. */
export function searchFieldGroups(
  source: SidebarSource,
  mode: SidebarMode,
  tab: SidebarTab,
  tmdbConfigured: boolean,
): SearchFieldGroup[] {
  const scope = sortScope(source, mode);
  const fields = keysOf(SEARCHES).filter((id) => {
    const field: SearchDef = SEARCHES[id];
    return tab === "movie" || !field.movieOnly;
  });
  if (scope !== "library") {
    return [
      {
        label: scope === "overturedb" ? "OvertureDB" : "Collections",
        fields: searchEntries(
          fields.filter((id) => search(id)?.[scope]),
          scope,
        ),
      },
    ];
  }
  const groups: SearchFieldGroup[] = [
    {
      label: "Library",
      fields: searchEntries(
        fields.filter((id) => search(id)?.library),
        scope,
      ),
    },
    {
      label: "TMDB",
      fields: searchEntries(
        fields.filter((id) => search(id)?.tmdb && tmdbConfigured),
        scope,
      ),
    },
  ];
  return groups.filter((group) => group.fields.length > 0);
}

/** The list a sidebar source and mode show. */
export function sortScope(source: SidebarSource, mode: SidebarMode): SortScope {
  if (source === "overturedb") return "overturedb";
  return mode === "collections" ? "collections" : "library";
}

/** What the search box says, naming the field or what it searches. */
export function searchPlaceholder(
  mode: SidebarMode,
  tab: SidebarTab,
  field: SidebarSearchField,
  count: number,
): string {
  const placeholder = search(field)?.placeholder;
  if (placeholder) return placeholder;
  if (mode === "collections") return `Search ${count} collection${count === 1 ? "" : "s"}...`;
  return `Search ${count} ${tab === "movie" ? "movies" : "shows"}...`;
}

function hasKey<K extends string>(record: Record<K, unknown>, key: string): key is K {
  return Object.hasOwn(record, key);
}

/** Where an item's theme ID came from; the file sources are read from its tags. */
export const THEME_SOURCE_LABELS: Record<ThemeSource, string> = {
  download: "Downloaded",
  embedded_id: "File ID tag",
  source_url: "File source link",
  metadata_url: "Other file link",
  selection: "Selected",
};
export const THEME_SOURCES = keysOf(THEME_SOURCE_LABELS);

/** Where an item's selected artwork comes from; OvertureDB's catalog art counts as its own. */
export const ART_SOURCE_LABELS: Record<ArtSource, string> = SELECTED_ART_SOURCE_LABELS;
export const ART_SOURCES = keysOf(ART_SOURCE_LABELS);

/** Which of a row's artwork the art source filter looks at. */
export const ART_SOURCE_SLOTS = {
  any: ["poster_source", "background_source"],
  poster: ["poster_source"],
  background: ["background_source"],
} as const satisfies Record<string, readonly (keyof MediaItemRead & keyof CollectionRead)[]>;
export type ArtSourceSlot = keyof typeof ART_SOURCE_SLOTS;

export type MetadataIssue =
  | "no_tmdb_id"
  | "no_tvdb_id"
  | "no_imdb_id"
  | "no_local_path"
  | "no_year"
  | "no_server_id"
  | "id_mismatch";

interface MetadataIssueCheck {
  label: string;
  showOnly?: boolean;
  /** Only checked while OvertureDB is enabled. */
  needsDataset?: boolean;
  library: (item: MediaItemRead) => boolean;
  /** Collections have only some of an item's metadata. */
  collections?: (collection: CollectionRead) => boolean;
}

export const METADATA_ISSUE_CHECKS: Record<MetadataIssue, MetadataIssueCheck> = {
  no_tmdb_id: {
    label: "No TMDB ID",
    library: (item) => !item.tmdb_id,
    collections: (collection) => !collection.tmdb_collection_id,
  },
  no_tvdb_id: { label: "No TVDB ID", showOnly: true, library: (item) => !item.tvdb_id },
  no_imdb_id: { label: "No IMDb ID", library: (item) => !item.imdb_id },
  no_local_path: { label: "No local path", library: (item) => !item.folder_path },
  no_year: { label: "No year", library: (item) => !item.year },
  no_server_id: {
    label: "No media server ID",
    library: (item) => !item.server_item_id,
    collections: (collection) => collection.withheld,
  },
  id_mismatch: {
    label: "ID mismatch",
    needsDataset: true,
    library: (item) => item.public_dataset_ids === "mismatching",
  },
};
export const METADATA_ISSUES = keysOf(METADATA_ISSUE_CHECKS);

/** Whether *flag* can be checked in the list: OvertureDB's issues need it enabled. */
function issueAvailable(
  flag: MetadataIssue,
  publicDatasetEnabled: boolean,
  mode: SidebarMode = "items",
): boolean {
  const check = METADATA_ISSUE_CHECKS[flag];
  return (publicDatasetEnabled || !check.needsDataset) && (mode === "items" || !!check.collections);
}

export function metadataIssuesFor(
  tab: SidebarTab,
  publicDatasetEnabled: boolean,
  mode: SidebarMode = "items",
): MetadataIssue[] {
  return METADATA_ISSUES.filter(
    (flag) =>
      (tab === "show" || !METADATA_ISSUE_CHECKS[flag].showOnly) &&
      issueAvailable(flag, publicDatasetEnabled, mode),
  );
}

export function hasThemeAttributes(
  item:
    | {
        youtube_id?: string | null;
        youtube_title?: string | null;
        youtube_duration?: number | null;
      }
    | null
    | undefined,
): boolean {
  return !!(item && (item.youtube_id || item.youtube_title || item.youtube_duration));
}

export function isRangeActive(range: NumberRange): boolean {
  return range.min !== null || range.max !== null;
}

/** Whether a known value lies within the inclusive range; unknown values never do. */
function inRange(value: number | null, range: NumberRange): boolean {
  return (
    value !== null &&
    (range.min === null || value >= range.min) &&
    (range.max === null || value <= range.max)
  );
}

function matchesTriState(value: boolean, filter: string, whenTrue: string): boolean {
  return filter === "all" || value === (filter === whenTrue);
}

type Predicate<T> = (entry: T) => boolean;
type Row = MediaItemRead | CollectionRead;

/**
 * One filter section: its heading, its place, and the predicate it adds for
 * each list it applies to, or ``null`` while it is left at All.
 */
/**
 * Where the filters popup places a filter: libraries first, then every
 * one-choice status filter together, then the art and theme refinements.
 */
export const FILTER_GROUPS = {
  libraries: null,
  status: "Status",
  art: "Art",
  theme: "Theme music",
  metadata: null,
} as const;
export type FilterGroup = keyof typeof FILTER_GROUPS;

interface FilterDef {
  label: string;
  group: FilterGroup;
  order: number;
  mediaTypes?: readonly SidebarTab[];
  /** Shown only while OvertureDB is enabled. */
  needsDataset?: boolean;
  /** Shown only where the server has smart collections. */
  needsSmart?: boolean;
  library?: (filters: FilterState, datasetEnabled: boolean) => Predicate<MediaItemRead> | null;
  collections?: (filters: FilterState, datasetEnabled: boolean) => Predicate<CollectionRead> | null;
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
  return (row) => slots.some((slot) => sources.has(row[slot]));
}

function resolutionPredicate(filters: FilterState): Predicate<Row> | null {
  if (!isRangeActive(filters.resolution)) return null;
  const width = filters.resolution.artType === "poster" ? "poster_width" : "background_width";
  return (row) => inRange(row[width], filters.resolution);
}

function issuesPredicate<T>(
  filters: FilterState,
  datasetEnabled: boolean,
  check: (flag: MetadataIssueCheck) => ((row: T) => boolean) | undefined,
): Predicate<T> | null {
  const checks = filters.metadataIssues.flags
    .filter((flag) => issueAvailable(flag, datasetEnabled))
    .flatMap((flag) => check(METADATA_ISSUE_CHECKS[flag]) ?? []);
  if (!checks.length) return null;
  return filters.metadataIssues.mode === "any"
    ? (row) => checks.some((applies) => applies(row))
    : (row) => checks.every((applies) => applies(row));
}

/** Every filter section, placed by ``order``, which follows ``FILTER_GROUPS``. */
export const FILTERS = {
  libraries: {
    label: "Libraries",
    group: "libraries",
    order: 10,
    library: (filters) =>
      filters.libraryIds.length
        ? (item) => !!item.library_id && filters.libraryIds.includes(item.library_id)
        : null,
    collections: (filters) =>
      filters.libraryIds.length
        ? (row) => !!row.library_id && filters.libraryIds.includes(row.library_id)
        : null,
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
    order: 40,
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
    order: 50,
    library: (filters) =>
      triState(filters.theme, "complete", (item) => item.theme_status === "complete"),
    collections: (filters) =>
      triState(filters.theme, "complete", (row) => row.theme_status === "complete"),
  },
  themeLength: {
    label: "Theme length",
    group: "theme",
    order: 300,
    library: (filters) =>
      isRangeActive(filters.themeLength)
        ? (item) => inRange(item.theme_duration, filters.themeLength)
        : null,
    collections: (filters) =>
      isRangeActive(filters.themeLength)
        ? (row) => inRange(row.theme_duration, filters.themeLength)
        : null,
  },
  themeSources: {
    label: "Theme source",
    group: "theme",
    order: 310,
    library: (filters) => {
      if (!filters.themeSources.length) return null;
      const sources = new Set(filters.themeSources);
      return (item) => !!item.youtube_id_source && sources.has(item.youtube_id_source);
    },
  },
  overtureDb: {
    label: "OvertureDB",
    group: "status",
    order: 60,
    needsDataset: true,
    library: (filters, datasetEnabled) =>
      datasetEnabled
        ? triState(filters.overtureDb, "complete", (item) => item.public_dataset_complete)
        : null,
    collections: (filters, datasetEnabled) =>
      datasetEnabled
        ? triState(filters.overtureDb, "complete", (row) => row.public_dataset_complete)
        : null,
  },
  themerrDb: {
    label: "ThemerrDB",
    group: "status",
    order: 70,
    needsDataset: true,
    library: (filters, datasetEnabled) =>
      datasetEnabled
        ? triState(filters.themerrDb, "complete", (item) => item.public_dataset_themerrdb)
        : null,
    collections: (filters, datasetEnabled) =>
      datasetEnabled
        ? triState(filters.themerrDb, "complete", (row) => row.public_dataset_themerrdb)
        : null,
  },
  metadataIssues: {
    label: "Metadata issues",
    group: "metadata",
    order: 400,
    library: (filters, datasetEnabled) =>
      issuesPredicate(filters, datasetEnabled, (check) => check.library),
    collections: (filters, datasetEnabled) =>
      issuesPredicate(filters, datasetEnabled, (check) => check.collections),
  },
  collectionMembers: {
    label: "Management",
    group: "status",
    order: 80,
    collections: (filters) => triState(filters.collectionMembers, "managed", (row) => row.managed),
  },
  collectionKind: {
    label: "Kind",
    group: "status",
    order: 90,
    needsSmart: true,
    collections: (filters) =>
      triState(filters.collectionKind, "smart", (row) => row.kind === "smart"),
  },
  collectionSync: {
    label: "Last sync",
    group: "status",
    order: 100,
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
    order: 110,
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
    order: 120,
    // Items the server removed are not listed, so only unlinked ones are missing.
    library: (filters) => triState(filters.mediaServer, "missing", (item) => !item.server_item_id),
    collections: (filters) => triState(filters.mediaServer, "missing", (row) => row.withheld),
  },
} as const satisfies Record<string, FilterDef>;
export type FilterKey = keyof typeof FILTERS;

/** The filter sections a list shows, in order. */
export function filterSections(
  mode: SidebarMode,
  options: { tab: SidebarTab; datasetEnabled: boolean; smart: boolean },
): FilterKey[] {
  const scope = mode === "collections" ? "collections" : "library";
  return keysOf(FILTERS)
    .filter((key) => {
      const filter: FilterDef = FILTERS[key];
      return (
        !!filter[scope] &&
        (!filter.mediaTypes || filter.mediaTypes.includes(options.tab)) &&
        (!filter.needsDataset || options.datasetEnabled) &&
        (!filter.needsSmart || options.smart)
      );
    })
    .sort((a, b) => FILTERS[a].order - FILTERS[b].order);
}

function libraryPredicates(
  filters: FilterState,
  datasetEnabled: boolean,
): Predicate<MediaItemRead>[] {
  return keysOf(FILTERS).flatMap((key) => {
    const filter: FilterDef = FILTERS[key];
    return filter.library?.(filters, datasetEnabled) ?? [];
  });
}

function collectionPredicates(
  filters: FilterState,
  datasetEnabled: boolean,
): Predicate<CollectionRead>[] {
  return keysOf(FILTERS).flatMap((key) => {
    const filter: FilterDef = FILTERS[key];
    return filter.collections?.(filters, datasetEnabled) ?? [];
  });
}

/** How many of the list's filters narrow it now. */
export function activeFilterCount(
  filters: FilterState,
  publicDatasetEnabled: boolean,
  mode: SidebarMode,
): number {
  return mode === "collections"
    ? collectionPredicates(filters, publicDatasetEnabled).length
    : libraryPredicates(filters, publicDatasetEnabled).length;
}

export function filterSidebarItems(options: {
  items: MediaItemRead[];
  filters: FilterState;
  publicDatasetEnabled: boolean;
  searchQuery: string;
  searchField: SidebarSearchField;
  sortField: SidebarSortField;
  sortDir: SidebarSortDir;
}): MediaItemRead[] {
  const predicates = libraryPredicates(options.filters, options.publicDatasetEnabled);
  const query = options.searchQuery.trim();
  const matcher = search(options.searchField)?.library;
  if (query && matcher) predicates.push(matcher(query));
  const items = options.items.filter((item) => predicates.every((matches) => matches(item)));
  return sortBy(items, "library", options.sortField, options.sortDir);
}

export function filterSidebarCollections(options: {
  collections: CollectionRead[];
  filters: FilterState;
  publicDatasetEnabled: boolean;
  searchQuery: string;
  searchField: SidebarSearchField;
  sortField: SidebarSortField;
  sortDir: SidebarSortDir;
}): CollectionRead[] {
  const predicates = collectionPredicates(options.filters, options.publicDatasetEnabled);
  const query = options.searchQuery.trim();
  const matcher = search(options.searchField)?.collections;
  if (query && matcher) predicates.push(matcher(query));
  const collections = options.collections.filter((collection) =>
    predicates.every((matches) => matches(collection)),
  );
  return sortBy(collections, "collections", options.sortField, options.sortDir);
}

const STATUS_TONES: Record<AssetStatus, StatusTone> = {
  complete: "success",
  partial: "warning",
  missing: "danger",
};

/**
 * The tone of an asset status the backend reported: the sidebar badges and the
 * detail page's section icons draw it with the `data-status` styles in app.css.
 */
export function statusTone(status: AssetStatus, downloading: boolean): StatusTone {
  return downloading ? "downloading" : STATUS_TONES[status];
}

/** Rows mounted beyond each edge of the sidebar's viewport, so they load before they show. */
export const SIDEBAR_OVERSCAN_ROWS = 20;

/** Screens of rows below and above the viewport whose posters are fetched ahead. */
const PRELOAD_SCREENS = 2;

/**
 * The rows whose posters to fetch ahead once scrolling settles, given the
 * rows on screen (`first` up to `end`): up to a screen past the mounted
 * rows, below first (the usual way on), each side nearest first.
 */
export function preloadRowIndexes(first: number, end: number, count: number): number[] {
  const span = Math.max(1, end - first) * PRELOAD_SCREENS;
  const belowStart = Math.min(count, end + SIDEBAR_OVERSCAN_ROWS);
  const belowEnd = Math.min(count, belowStart + span);
  const aboveEnd = Math.max(0, first - SIDEBAR_OVERSCAN_ROWS);
  const aboveStart = Math.max(0, aboveEnd - span);
  return [
    ...Array.from({ length: belowEnd - belowStart }, (_, offset) => belowStart + offset),
    ...Array.from({ length: aboveEnd - aboveStart }, (_, offset) => aboveEnd - 1 - offset),
  ];
}

/**
 * Whether a collection is listed under *group*, or at the top level for null.
 * The virtual Unmanaged group holds every collection without a rule, so those
 * appear nowhere else.
 */
export function inCollectionGroup(
  collection: Pick<CollectionRead, "collection_group" | "managed">,
  group: string | null,
): boolean {
  if (!collection.managed) return group === UNMANAGED_GROUP;
  return group !== UNMANAGED_GROUP && (collection.collection_group ?? null) === group;
}
