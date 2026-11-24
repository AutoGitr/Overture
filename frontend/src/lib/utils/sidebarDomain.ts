import type {
  CatalogEntryRow,
  CollectionRead,
  MediaItemRead,
} from "../../generated/rest/types.gen";

import { keysOf } from "./records";
import {
  collectionPredicates,
  libraryPredicates,
  type CatalogFilters,
  type TmdbFilterKey,
  type TmdbFilters,
} from "./sidebarFilters";
import { searchDef, type SidebarSearchField } from "./sidebarSearches";
import { matchesTriState, type SidebarSortDir } from "./sidebarShared";
import { sortBy, type SidebarSortField } from "./sidebarSorts";
import type { FilterState } from "../stores/filterState.svelte";

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
  const matcher = query ? searchDef(options.searchField ?? "title")?.overturedb : undefined;
  const matching = matcher ? rows.filter(matcher(query)) : rows;
  return sortBy(matching, "overturedb", options.sortField, options.sortDir);
}

/** TMDB results the filters keep, in the chosen order. */
export function arrangeTmdbResults<T extends { title: string; year?: number | null }>(options: {
  results: T[];
  held: (result: T) => Record<TmdbFilterKey, boolean>;
  filters: TmdbFilters;
  keys: readonly TmdbFilterKey[];
  sortField: SidebarSortField;
  sortDir: SidebarSortDir;
}): T[] {
  const kept = options.results
    .map((result, rank) => ({ result, rank, title: result.title, year: result.year ?? null }))
    .filter(({ result }) => {
      const held = options.held(result);
      return options.keys.every((key) =>
        matchesTriState(held[key], options.filters[key], "present"),
      );
    });
  return sortBy(kept, "tmdb", options.sortField, options.sortDir).map(({ result }) => result);
}

export function filterSidebarItems(options: {
  items: MediaItemRead[];
  filters: FilterState;
  catalogEnabled: boolean;
  collectionMembers?: ReadonlySet<number>;
  /** The saved custom filter's test, when one applies. */
  customFilter?: ((item: MediaItemRead) => boolean) | null;
  searchQuery: string;
  searchField: SidebarSearchField;
  sortField: SidebarSortField;
  sortDir: SidebarSortDir;
}): MediaItemRead[] {
  const predicates = libraryPredicates(
    options.filters,
    options.catalogEnabled,
    options.collectionMembers,
  );
  if (options.customFilter) predicates.push(options.customFilter);
  const query = options.searchQuery.trim();
  const matcher = searchDef(options.searchField)?.library;
  if (query && matcher) predicates.push(matcher(query));
  const items = options.items.filter((item) => predicates.every((matches) => matches(item)));
  return sortBy(items, "library", options.sortField, options.sortDir);
}

export function filterSidebarCollections(options: {
  collections: CollectionRead[];
  filters: FilterState;
  catalogEnabled: boolean;
  searchQuery: string;
  searchField: SidebarSearchField;
  sortField: SidebarSortField;
  sortDir: SidebarSortDir;
}): CollectionRead[] {
  const predicates = collectionPredicates(options.filters, options.catalogEnabled);
  const query = options.searchQuery.trim();
  const matcher = searchDef(options.searchField)?.collections;
  if (query && matcher) predicates.push(matcher(query));
  const collections = options.collections.filter((collection) =>
    predicates.every((matches) => matches(collection)),
  );
  return sortBy(collections, "collections", options.sortField, options.sortDir);
}
