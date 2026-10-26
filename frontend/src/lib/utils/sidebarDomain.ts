import { SELECTED_ART_SOURCE_LABELS } from "../../generated/settings";
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
  const query = options.searchQuery.trim().toLowerCase();
  const linkedId = extractYouTubeId(query) ?? query;
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
    if (
      !keysOf(filters).every(
        (key) =>
          (key === "seasonPosters" && entry.media_type !== "show") ||
          matchesTriState(presence[key], filters[key], "present"),
      )
    )
      return false;
    if (!query) return true;
    if (options.searchField === "external_id")
      return [entry.tmdb_id, entry.tvdb_id, entry.imdb_id].some(
        (id) => id != null && String(id).toLowerCase() === query,
      );
    if (options.searchField === "year") return String(entry.year ?? "").startsWith(query);
    if (options.searchField === "youtube")
      return [entry.youtube_id_overturedb, entry.youtube_id_themerrdb].some(
        (id) => id?.toLowerCase() === linkedId.toLowerCase(),
      );
    return entry.title.toLowerCase().includes(query);
  });
  return rows.sort((a, b) => {
    const direction = options.sortDir === "desc" ? -1 : 1;
    if (options.sortField === "year" && a.year !== b.year) {
      if (a.year === null) return 1;
      if (b.year === null) return -1;
      return (a.year - b.year) * direction;
    }
    return titleCollator.compare(a.title, b.title) * direction;
  });
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
export type ArtSource = NonNullable<MediaItemRead["poster_source"]>;
export type AssetStatus = MediaItemRead["art_status"];

const titleCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function timestamp(value: string | null): number | null {
  return value ? Date.parse(value) : null;
}

type ItemSortField =
  | "title"
  | "year"
  | "server_added_at"
  | "last_synced_at"
  | "last_matched_at"
  | "poster_resolution"
  | "background_resolution"
  | "theme_length";
type CollectionSortField =
  "title" | "sort_title" | "child_count" | "server_added_at" | "last_rule_sync" | "theme_length";
export type SidebarSortField = ItemSortField | CollectionSortField;

/** Which list a sort applies to; each remembers its own. */
export type SortScope = "library" | "collections" | "overturedb";

type SortKey = number | string | null;

interface SortOption<T> {
  label: string;
  shortLabel: string;
  /** Sort key; titles sort by collation. Rows without one stay last. */
  value: (row: T) => SortKey;
}

/** Sort fields in menu order. */
export const SIDEBAR_SORT_OPTIONS: Record<ItemSortField, SortOption<MediaItemRead>> = {
  title: { label: "Title", shortLabel: "Title", value: (item) => item.title },
  year: { label: "Year", shortLabel: "Year", value: (item) => item.year },
  server_added_at: {
    label: "Date added",
    shortLabel: "Added",
    value: (item) => timestamp(item.server_added_at),
  },
  last_synced_at: {
    label: "Last synced",
    shortLabel: "Synced",
    value: (item) => timestamp(item.last_synced_at),
  },
  last_matched_at: {
    label: "Last matched",
    shortLabel: "Matched",
    value: (item) => timestamp(item.last_matched_at),
  },
  poster_resolution: {
    label: "Poster width",
    shortLabel: "Poster",
    value: (item) => item.poster_width,
  },
  background_resolution: {
    label: "Background width",
    shortLabel: "Background",
    value: (item) => item.background_width,
  },
  theme_length: {
    label: "Theme length",
    shortLabel: "Theme",
    value: (item) => item.theme_duration,
  },
};

export const COLLECTION_SORT_OPTIONS: Record<CollectionSortField, SortOption<CollectionRead>> = {
  title: { label: "Title", shortLabel: "Title", value: (collection) => collection.title },
  sort_title: {
    label: "Sort title (media server order)",
    shortLabel: "Sort title",
    value: (collection) => collection.sort_title || collection.title,
  },
  child_count: {
    label: "Number of items",
    shortLabel: "Items",
    value: (collection) => collection.child_count,
  },
  server_added_at: {
    label: "Date added",
    shortLabel: "Added",
    value: (collection) => timestamp(collection.server_added_at),
  },
  last_rule_sync: {
    label: "Last synced",
    shortLabel: "Synced",
    value: (collection) => timestamp(collection.last_rule_sync),
  },
  theme_length: {
    label: "Theme length",
    shortLabel: "Theme",
    value: (collection) => collection.theme_duration,
  },
};

const CATALOG_SORT_FIELDS: readonly ItemSortField[] = ["title", "year"];

export interface MenuEntry<F extends string> {
  id: F;
  label: string;
  shortLabel: string;
}

function menu<F extends SidebarSortField, T>(
  options: Record<F, SortOption<T>>,
  fields: readonly F[],
): MenuEntry<SidebarSortField>[] {
  return fields.map((id) => ({ id, label: options[id].label, shortLabel: options[id].shortLabel }));
}

/** The sort fields a list offers, in menu order. */
export function sortMenu(scope: SortScope): MenuEntry<SidebarSortField>[] {
  if (scope === "collections")
    return menu(COLLECTION_SORT_OPTIONS, keysOf(COLLECTION_SORT_OPTIONS));
  return menu(
    SIDEBAR_SORT_OPTIONS,
    scope === "overturedb" ? CATALOG_SORT_FIELDS : keysOf(SIDEBAR_SORT_OPTIONS),
  );
}

export type SidebarSortPreference = { field: SidebarSortField; dir: SidebarSortDir };

export function defaultSortDir(field: SidebarSortField): SidebarSortDir {
  return field === "title" || field === "sort_title" ? "asc" : "desc";
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

type ItemSearchField =
  "title" | "director" | "studio" | "year" | "external_id" | "youtube" | "tmdb";
type CollectionSearchField = "title" | "group" | "external_id" | "youtube";
export type SidebarSearchField = ItemSearchField | CollectionSearchField;

interface SearchFieldOption<T> {
  label: string;
  placeholder?: string;
  movieOnly?: boolean;
  /**
   * Builds the row predicate for one trimmed, non-empty query. A field
   * without one searches TMDB on the server instead of filtering the library.
   */
  matcher?: (query: string) => (row: T) => boolean;
}

function textMatcher<T>(text: (row: T) => string | null) {
  return (query: string) => {
    const needle = query.toLowerCase();
    return (row: T) => text(row)?.toLowerCase().includes(needle) ?? false;
  };
}

function youtubeMatcher<T>(ids: (row: T) => (string | null)[], title: (row: T) => string | null) {
  return (query: string) => {
    const linkedId = extractYouTubeId(query);
    const needle = query.toLowerCase();
    return (row: T) =>
      linkedId
        ? ids(row).includes(linkedId)
        : ids(row).some((id) => id?.toLowerCase() === needle) ||
          (title(row)?.toLowerCase().includes(needle) ?? false);
  };
}

/** Search fields in menu order. */
export const SIDEBAR_SEARCH_FIELDS: Record<ItemSearchField, SearchFieldOption<MediaItemRead>> = {
  title: {
    label: "Title",
    matcher: textMatcher((item) => item.title),
  },
  director: {
    label: "Director",
    placeholder: "Search directors...",
    movieOnly: true,
    matcher: textMatcher((item) => (item.media_type === "movie" ? item.director : null)),
  },
  studio: {
    label: "Studio",
    placeholder: "Search studios...",
    matcher: textMatcher((item) => item.studio),
  },
  year: {
    label: "Year",
    placeholder: "Search years...",
    matcher: (query) => (item) => String(item.year ?? "").startsWith(query),
  },
  external_id: {
    label: "TMDB, TVDB or IMDb ID",
    placeholder: "Search IDs...",
    matcher: (query) => {
      // A pasted IMDb link carries its ID; every other ID must match exactly.
      const id = (/tt\d+/i.exec(query)?.[0] ?? query).toLowerCase();
      return (item) =>
        [item.tmdb_id, item.tvdb_id, item.imdb_id].some(
          (value) => value != null && String(value).toLowerCase() === id,
        );
    },
  },
  youtube: {
    label: "YouTube link, ID or title",
    placeholder: "Search YouTube...",
    matcher: youtubeMatcher(
      (item) => [item.youtube_id],
      (item) => item.youtube_title,
    ),
  },
  tmdb: {
    // Listed under a "TMDB" heading, apart from the library fields.
    label: "Title or ID",
    placeholder: "Search TMDB by title or ID...",
  },
};

export const COLLECTION_SEARCH_FIELDS: Record<
  CollectionSearchField,
  SearchFieldOption<CollectionRead>
> = {
  title: {
    label: "Title",
    matcher: textMatcher((collection) => collection.title),
  },
  group: {
    label: "Group",
    placeholder: "Search groups...",
    matcher: textMatcher((collection) => collection.collection_group),
  },
  external_id: {
    label: "TMDB collection ID",
    placeholder: "Search TMDB IDs...",
    matcher: (query) => (collection) => String(collection.tmdb_collection_id ?? "") === query,
  },
  youtube: {
    label: "YouTube link, ID or title",
    placeholder: "Search YouTube...",
    matcher: youtubeMatcher(
      (collection) => [collection.youtube_id],
      (collection) => collection.youtube_title,
    ),
  },
};

export interface SearchFieldGroup {
  label: "Library" | "TMDB" | "OvertureDB" | "Collections";
  fields: MenuEntry<SidebarSearchField>[];
}

function entries<F extends SidebarSearchField>(
  options: Partial<Record<F, SearchFieldOption<never>>>,
  fields: readonly F[],
): MenuEntry<SidebarSearchField>[] {
  return fields.flatMap((id) => {
    const option = options[id];
    return option ? [{ id, label: option.label, shortLabel: option.label }] : [];
  });
}

/** The search fields a list offers; library fields first, then TMDB's. */
export function searchFieldGroups(
  source: SidebarSource,
  mode: SidebarMode,
  tab: SidebarTab,
  tmdbConfigured: boolean,
): SearchFieldGroup[] {
  if (source === "overturedb") {
    return [
      {
        label: "OvertureDB",
        fields: entries(SIDEBAR_SEARCH_FIELDS, ["title", "year", "external_id", "youtube"]),
      },
    ];
  }
  if (mode === "collections") {
    return [
      {
        label: "Collections",
        fields: entries(COLLECTION_SEARCH_FIELDS, keysOf(COLLECTION_SEARCH_FIELDS)),
      },
    ];
  }
  const fields = searchFieldsFor(tab, tmdbConfigured);
  const groups: SearchFieldGroup[] = [
    {
      label: "Library",
      fields: entries(
        SIDEBAR_SEARCH_FIELDS,
        fields.filter((field) => SIDEBAR_SEARCH_FIELDS[field].matcher),
      ),
    },
    {
      label: "TMDB",
      fields: entries(
        SIDEBAR_SEARCH_FIELDS,
        fields.filter((field) => !SIDEBAR_SEARCH_FIELDS[field].matcher),
      ),
    },
  ];
  return groups.filter((group) => group.fields.length > 0);
}

/** The search fields a tab offers; TMDB only while an API key is set. */
export function searchFieldsFor(tab: SidebarTab, tmdbConfigured: boolean): ItemSearchField[] {
  return keysOf(SIDEBAR_SEARCH_FIELDS).filter(
    (field) =>
      (tab === "movie" || !SIDEBAR_SEARCH_FIELDS[field].movieOnly) &&
      (field !== "tmdb" || tmdbConfigured),
  );
}

/** What the search box says, naming the field or what it searches. */
export function searchPlaceholder(
  mode: SidebarMode,
  tab: SidebarTab,
  field: SidebarSearchField,
  count: number,
): string {
  const options: Partial<Record<SidebarSearchField, SearchFieldOption<never>>> =
    mode === "collections" ? COLLECTION_SEARCH_FIELDS : SIDEBAR_SEARCH_FIELDS;
  const placeholder = options[field]?.placeholder;
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

/** Which of an item's artwork the art source filter looks at. */
export const ART_SOURCE_SLOTS = {
  any: ["poster_source", "background_source"],
  poster: ["poster_source"],
  background: ["background_source"],
} as const satisfies Record<string, readonly (keyof MediaItemRead)[]>;
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
  applies: (item: MediaItemRead) => boolean;
}

export const METADATA_ISSUE_CHECKS: Record<MetadataIssue, MetadataIssueCheck> = {
  no_tmdb_id: { label: "No TMDB ID", applies: (item) => !item.tmdb_id },
  no_tvdb_id: { label: "No TVDB ID", showOnly: true, applies: (item) => !item.tvdb_id },
  no_imdb_id: { label: "No IMDb ID", applies: (item) => !item.imdb_id },
  no_local_path: { label: "No local path", applies: (item) => !item.folder_path },
  no_year: { label: "No year", applies: (item) => !item.year },
  no_server_id: { label: "No media server ID", applies: (item) => !item.server_item_id },
  id_mismatch: {
    label: "ID mismatch",
    needsDataset: true,
    applies: (item) => item.public_dataset_ids === "mismatching",
  },
};
export const METADATA_ISSUES = keysOf(METADATA_ISSUE_CHECKS);

/** Whether *flag* can be checked: OvertureDB's issues need it enabled. */
function issueAvailable(flag: MetadataIssue, publicDatasetEnabled: boolean): boolean {
  return publicDatasetEnabled || !METADATA_ISSUE_CHECKS[flag].needsDataset;
}

export function metadataIssuesFor(tab: SidebarTab, publicDatasetEnabled: boolean): MetadataIssue[] {
  return METADATA_ISSUES.filter(
    (flag) =>
      (tab === "show" || !METADATA_ISSUE_CHECKS[flag].showOnly) &&
      issueAvailable(flag, publicDatasetEnabled),
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

/** Filters both items and collections apply. */
function sharedPredicates(filters: FilterState): Predicate<MediaItemRead | CollectionRead>[] {
  const predicates: Predicate<MediaItemRead | CollectionRead>[] = [];
  if (filters.monitored !== "all") {
    predicates.push((entry) => matchesTriState(entry.monitored, filters.monitored, "monitored"));
  }
  if (filters.libraryIds.length) {
    predicates.push((entry) => !!entry.library_id && filters.libraryIds.includes(entry.library_id));
  }
  if (filters.theme !== "all") {
    predicates.push((entry) =>
      matchesTriState(entry.theme_status === "complete", filters.theme, "complete"),
    );
  }
  if (isRangeActive(filters.themeLength)) {
    predicates.push((entry) => inRange(entry.theme_duration, filters.themeLength));
  }
  return predicates;
}

export function hasVisibleActiveFilters(
  filters: FilterState,
  publicDatasetEnabled: boolean,
  mode: SidebarMode,
): boolean {
  const shared =
    filters.monitored !== "all" ||
    filters.theme !== "all" ||
    filters.libraryIds.length > 0 ||
    isRangeActive(filters.themeLength);
  if (mode === "collections")
    return (
      shared ||
      filters.collectionSize !== "all" ||
      filters.collectionKind !== "all" ||
      filters.collectionMembers !== "all" ||
      filters.collectionSync !== "all" ||
      filters.art !== "all" ||
      filters.mediaServer !== "all" ||
      (publicDatasetEnabled && (filters.overtureDb !== "all" || filters.themerrDb !== "all"))
    );
  return (
    shared ||
    filters.art !== "all" ||
    (publicDatasetEnabled && filters.overtureDb !== "all") ||
    (publicDatasetEnabled && filters.themerrDb !== "all") ||
    filters.aspectRatio !== "all" ||
    filters.mediaServer !== "all" ||
    filters.themeSources.length > 0 ||
    filters.artSource.sources.length > 0 ||
    filters.metadataIssues.flags.some((flag) => issueAvailable(flag, publicDatasetEnabled)) ||
    isRangeActive(filters.resolution)
  );
}

function itemPredicates(
  filters: FilterState,
  publicDatasetEnabled: boolean,
): Predicate<MediaItemRead>[] {
  const predicates: Predicate<MediaItemRead>[] = sharedPredicates(filters);
  if (filters.art !== "all") {
    predicates.push((item) =>
      matchesTriState(item.art_status === "complete", filters.art, "complete"),
    );
  }
  if (publicDatasetEnabled && filters.overtureDb !== "all") {
    predicates.push((item) =>
      matchesTriState(item.public_dataset_complete, filters.overtureDb, "complete"),
    );
  }
  if (publicDatasetEnabled && filters.themerrDb !== "all") {
    predicates.push((item) =>
      matchesTriState(item.public_dataset_themerrdb, filters.themerrDb, "complete"),
    );
  }
  if (filters.aspectRatio !== "all") {
    predicates.push((item) =>
      matchesTriState(item.has_incorrect_aspect_ratio, filters.aspectRatio, "incorrect"),
    );
  }
  if (filters.mediaServer !== "all") {
    predicates.push((item) =>
      // Items the server removed are not listed, so only unlinked ones are missing.
      matchesTriState(!item.server_item_id, filters.mediaServer, "missing"),
    );
  }
  if (filters.themeSources.length) {
    const sources = new Set(filters.themeSources);
    predicates.push((item) => !!item.youtube_id_source && sources.has(item.youtube_id_source));
  }
  if (filters.artSource.sources.length) {
    const sources = new Set<string | null>(filters.artSource.sources);
    const slots = ART_SOURCE_SLOTS[filters.artSource.artType];
    predicates.push((item) => slots.some((slot) => sources.has(item[slot])));
  }
  if (isRangeActive(filters.resolution)) {
    const width = filters.resolution.artType === "poster" ? "poster_width" : "background_width";
    predicates.push((item) => inRange(item[width], filters.resolution));
  }
  const { mode } = filters.metadataIssues;
  const flags = filters.metadataIssues.flags.filter((flag) =>
    issueAvailable(flag, publicDatasetEnabled),
  );
  if (flags.length) {
    const checks = flags.map((flag) => METADATA_ISSUE_CHECKS[flag].applies);
    predicates.push((item) =>
      mode === "any" ? checks.some((check) => check(item)) : checks.every((check) => check(item)),
    );
  }
  return predicates;
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
  const predicates = itemPredicates(options.filters, options.publicDatasetEnabled);
  const query = options.searchQuery.trim();
  const matcher = hasKey(SIDEBAR_SEARCH_FIELDS, options.searchField)
    ? SIDEBAR_SEARCH_FIELDS[options.searchField].matcher
    : undefined;
  if (query && matcher) predicates.push(matcher(query));
  const items = options.items.filter((item) => predicates.every((matches) => matches(item)));
  const sort = hasKey(SIDEBAR_SORT_OPTIONS, options.sortField)
    ? SIDEBAR_SORT_OPTIONS[options.sortField]
    : SIDEBAR_SORT_OPTIONS.title;
  return sortRows(items, sort.value, options.sortDir);
}

function collectionPredicates(
  filters: FilterState,
  publicDatasetEnabled: boolean,
): Predicate<CollectionRead>[] {
  const predicates: Predicate<CollectionRead>[] = sharedPredicates(filters);
  const triState = (
    filter: string,
    whenTrue: string,
    value: (collection: CollectionRead) => boolean,
  ) => {
    if (filter !== "all") predicates.push((row) => matchesTriState(value(row), filter, whenTrue));
  };
  triState(filters.art, "complete", (collection) => collection.art_status === "complete");
  triState(filters.mediaServer, "missing", (collection) => collection.withheld);
  triState(filters.collectionKind, "smart", (collection) => collection.kind === "smart");
  triState(filters.collectionMembers, "criteria", (collection) => collection.managed);
  if (publicDatasetEnabled) {
    triState(filters.overtureDb, "complete", (collection) => collection.public_dataset_complete);
    triState(filters.themerrDb, "complete", (collection) => collection.public_dataset_themerrdb);
  }
  if (filters.collectionSync !== "all") {
    // Only collections with criteria sync.
    predicates.push(
      (collection) =>
        collection.managed &&
        matchesTriState(collection.sync_failed, filters.collectionSync, "failed"),
    );
  }
  if (filters.collectionSize === "empty")
    predicates.push((collection) => collection.child_count === 0);
  if (filters.collectionSize === "below_minimum")
    predicates.push((collection) => collection.below_minimum);
  return predicates;
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
  const matcher = hasKey(COLLECTION_SEARCH_FIELDS, options.searchField)
    ? COLLECTION_SEARCH_FIELDS[options.searchField].matcher
    : undefined;
  if (query && matcher) predicates.push(matcher(query));
  const collections = options.collections.filter((collection) =>
    predicates.every((matches) => matches(collection)),
  );
  const sort = hasKey(COLLECTION_SORT_OPTIONS, options.sortField)
    ? COLLECTION_SORT_OPTIONS[options.sortField]
    : COLLECTION_SORT_OPTIONS.title;
  return sortRows(collections, sort.value, options.sortDir);
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
