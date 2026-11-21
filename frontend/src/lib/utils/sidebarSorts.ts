import type {
  CatalogEntryRow,
  CollectionRead,
  MediaItemRead,
} from "../../generated/rest/types.gen";
import { ASPECT_RATIOS, UNMANAGED_GROUP } from "../../generated/settings";
import { keysOf } from "./records";
import {
  hasKey,
  inCollectionGroup,
  timestamp,
  titleCollator,
  type CollectionGroupRow,
  type MenuEntry,
  type SidebarSortDir,
  type SortScope,
  type TmdbRow,
} from "./sidebarShared";

type SortKey = number | string | null;

/** One sort, by the list it applies to: the row's key, where rows without one stay last. */
interface SortDef {
  label: string;
  shortLabel: string;
  library?: (row: MediaItemRead) => SortKey;
  collections?: (row: CollectionRead) => SortKey;
  overturedb?: (row: CatalogEntryRow) => SortKey;
  groups?: (row: CollectionGroupRow) => SortKey;
  tmdb?: (row: TmdbRow) => SortKey;
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

/** Every sort, in menu order; a list's first sort is its default. */
const SORTS = {
  relevance: {
    label: "Relevance",
    shortLabel: "Relevance",
    tmdb: (row) => row.rank,
  },
  title: {
    label: "Title",
    shortLabel: "Title",
    tmdb: (row) => row.title,
    // The server's sort title leaves out "The", "A" and the like, as the server lists it.
    library: (item) => item.sort_title || item.title,
    collections: (collection) => collection.title,
    overturedb: (entry) => entry.title,
    groups: (group) => group.title,
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
    tmdb: (row) => row.year,
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
  collection_count: {
    label: "Number of collections",
    shortLabel: "Collections",
    groups: (group) => group.collections,
  },
  child_count: {
    label: "Number of items",
    shortLabel: "Items",
    collections: (collection) => collection.child_count,
    groups: (group) => group.items,
  },
  server_added_at: {
    label: "Date added",
    shortLabel: "Added",
    library: (item) => timestamp(item.server_added_at),
    collections: (collection) => timestamp(collection.server_added_at),
    groups: (group) => group.added,
  },
  last_synced_at: {
    label: "Last synced",
    shortLabel: "Synced",
    library: (item) => timestamp(item.last_synced_at),
    collections: (collection) => timestamp(collection.last_rule_sync),
    groups: (group) => group.synced,
  },
  last_matched_at: {
    label: "Last matched",
    shortLabel: "Matched",
    library: (item) => timestamp(item.last_matched_at),
  },
  poster_resolution: {
    label: "Poster width",
    shortLabel: "Poster",
    library: (item) => item.assets.poster.width,
  },
  background_resolution: {
    label: "Background width",
    shortLabel: "Background",
    library: (item) => item.assets.background.width,
  },
  poster_aspect: {
    label: "Poster aspect deviation",
    shortLabel: "Poster shape",
    library: (item) =>
      aspectDeviation(item.assets.poster.width, item.assets.poster.height, "poster"),
  },
  background_aspect: {
    label: "Background aspect deviation",
    shortLabel: "Background shape",
    library: (item) =>
      aspectDeviation(item.assets.background.width, item.assets.background.height, "background"),
  },
  theme_length: {
    label: "Theme length",
    shortLabel: "Theme",
    library: (item) => item.assets.theme.duration,
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

function sortKey(field: string, scope: SortScope): ((row: never) => SortKey) | undefined {
  const sort: SortDef | undefined = hasKey(SORTS, field) ? SORTS[field] : undefined;
  return sort?.[scope];
}

/**
 * The sort fields a list offers, in menu order, without those that say nothing
 * about it: every collection in an open group has that group, and only Plex
 * has a Home order.
 */
export function sortMenu(
  scope: SortScope,
  context: { inGroup?: boolean; plex?: boolean } = {},
): MenuEntry<SidebarSortField>[] {
  const pointless = new Set<SidebarSortField>([
    ...(context.inGroup ? (["group"] as const) : []),
    ...(context.plex === false ? (["home_order"] as const) : []),
  ]);
  return keysOf(SORTS)
    .filter((id) => sortKey(id, scope) && !pointless.has(id))
    .map((id) => ({ id, label: SORTS[id].label, shortLabel: SORTS[id].shortLabel }));
}

export type SidebarSortPreference = { field: SidebarSortField; dir: SidebarSortDir };

const ASCENDING_SORTS: ReadonlySet<SidebarSortField> = new Set([
  "relevance",
  "title",
  "sort_title",
  "group",
  "home_order",
]);

/** Names and orders read A to Z; measures, dates and deviations worst or newest first. */
export function defaultSortDir(field: SidebarSortField): SidebarSortDir {
  return ASCENDING_SORTS.has(field) ? "asc" : "desc";
}

/** A list's default sort: its first, ascending. */
export function defaultSort(fields: readonly MenuEntry<SidebarSortField>[]): SidebarSortPreference {
  return { field: fields[0]?.id ?? "title", dir: "asc" };
}

export function normalizeSortPreference(value: unknown, scope: SortScope): SidebarSortPreference {
  const stored = value && typeof value === "object" ? value : {};
  const field = "field" in stored ? stored.field : undefined;
  const dir = "dir" in stored ? stored.dir : undefined;
  const menu = sortMenu(scope);
  return {
    field: menu.find((entry) => entry.id === field)?.id ?? defaultSort(menu).field,
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

/** The groups as the sidebar lists them, from the collections the filters match. */
export function collectionGroupRows(
  names: readonly string[],
  collections: readonly CollectionRead[],
): CollectionGroupRow[] {
  const latest = (values: (string | null)[]) =>
    Math.max(...values.map((value) => timestamp(value) ?? -Infinity));
  return names.map((title) => {
    const held = collections.filter((row) => inCollectionGroup(row, title));
    const added = latest(held.map((row) => row.server_added_at));
    const synced = latest(held.map((row) => row.last_rule_sync));
    return {
      title,
      collections: held.length,
      items: held.reduce((total, row) => total + row.child_count, 0),
      added: Number.isFinite(added) ? added : null,
      synced: Number.isFinite(synced) ? synced : null,
    };
  });
}

/** Sorts the groups, keeping the unmanaged collections last whatever the order. */
export function sortCollectionGroups(
  groups: CollectionGroupRow[],
  field: SidebarSortField,
  dir: SidebarSortDir,
): CollectionGroupRow[] {
  const unmanaged = groups.filter((group) => group.title === UNMANAGED_GROUP);
  const named = groups.filter((group) => group.title !== UNMANAGED_GROUP);
  return [...sortBy(named, "groups", field, dir), ...unmanaged];
}

export function sortBy<T extends { title: string }>(
  rows: T[],
  scope: SortScope,
  field: string | undefined,
  dir: SidebarSortDir | undefined,
): T[] {
  // A list's own sorts take its row type; an unknown field sorts by title.
  const key = (sortKey(field ?? "title", scope) ?? sortKey("title", scope)) as (row: T) => SortKey;
  return sortRows(rows, key, dir ?? "asc");
}
