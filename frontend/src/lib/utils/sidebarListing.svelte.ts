import { createQuery } from "@tanstack/svelte-query";
import type { MediaItemRead } from "../../generated/rest/types.gen";
import {
  listCatalogEntriesOptions,
  listCollectionGroupsOptions,
  listCollectionsOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import { sidebarGroup } from "../router/routes";
import { settingsState } from "../stores/settingsState.svelte";
import { uiState } from "../stores/uiState.svelte";
import { CatalogBrowsing } from "./catalogBrowsing.svelte";
import { CollectionMembers } from "./collectionMembers.svelte";
import { CustomFilterMatch } from "./customFilterMatch.svelte";
import { catalogRowRecord, collectionRecord, type AdvanceRecord } from "./recordAdvance";
import {
  filterCatalogEntries,
  filterSidebarCollections,
  filterSidebarItems,
} from "./sidebarDomain";
import { tmdbFilterKeysFor } from "./sidebarFilters";
import {
  sidebarGroupNames,
  inCollectionGroup,
  type SidebarSortDir,
  type SidebarTab,
  type SortScope,
} from "./sidebarShared";
import {
  collectionGroupRows,
  defaultSort,
  normalizeSortPreference,
  sortCollectionGroups,
  sortMenu,
  type SidebarSortField,
  type SidebarSortPreference,
} from "./sidebarSorts";
import { readJson, writeJson } from "./storage";
import { filterState } from "../stores/filterState.svelte";

/** The library titles the app has loaded, which the sidebar lists. */
export interface SidebarLibrary {
  movies: MediaItemRead[];
  shows: MediaItemRead[];
  loading: boolean;
  error: string;
}

const SORT_KEYS: Record<SortScope, string> = {
  library: "overture_sidebar_sort",
  collections: "overture_collection_sort",
  groups: "overture_group_sort",
  overturedb: "overture_catalog_sort",
  tmdb: "overture_tmdb_sort",
};

function loadSortPreferences(scope: SortScope): Record<SidebarTab, SidebarSortPreference> {
  const load = (tab: SidebarTab) =>
    normalizeSortPreference(readJson<unknown>(`${SORT_KEYS[scope]}_${tab}`, null), scope);
  return { movie: load("movie"), show: load("show") };
}

/**
 * What the sidebar lists, in the order it shows it: the titles, collections,
 * groups or catalog entries its scope, filters, search and sort choose.
 */
export class SidebarListing {
  readonly catalog = new CatalogBrowsing();
  readonly collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions(),
    enabled: settingsState.current.collections_supported && uiState.sidebarSource === "library",
  }));
  readonly groupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions(),
    enabled: settingsState.current.collections_supported && uiState.sidebarSource === "library",
  }));
  readonly catalogMovies = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "movie" } }),
    enabled: this.catalog.browsable && uiState.sidebarSource === "overturedb",
  }));
  readonly catalogShows = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "show" } }),
    enabled: this.catalog.browsable && uiState.sidebarSource === "overturedb",
  }));
  readonly catalogCollections = createQuery(() => ({
    ...listCatalogEntriesOptions({
      query: { media_type: "collection", posters: uiState.catalogPosters },
    }),
    enabled: this.catalog.browsable && uiState.sidebarSource === "overturedb",
  }));
  readonly #customFilter = new CustomFilterMatch(() =>
    uiState.sidebarMode === "items"
      ? { mediaType: uiState.sidebarTab, filterId: filterState.current.customFilter }
      : null,
  );
  readonly #filteredCollection = new CollectionMembers(() =>
    uiState.sidebarMode === "items" ? filterState.current.collectionId : null,
  );
  /** Items, collections, groups and the catalog each remember their sort per tab. */
  #sortByScope = $state<Record<SortScope, Record<SidebarTab, SidebarSortPreference>>>({
    library: loadSortPreferences("library"),
    collections: loadSortPreferences("collections"),
    groups: loadSortPreferences("groups"),
    overturedb: loadSortPreferences("overturedb"),
    tmdb: loadSortPreferences("tmdb"),
  });

  constructor(private readonly library: () => SidebarLibrary) {}

  readonly collections = $derived(this.collectionsQuery.data ?? []);
  readonly catalogQuery = $derived(
    uiState.sidebarMode === "collections"
      ? this.catalogCollections
      : uiState.sidebarTab === "show"
        ? this.catalogShows
        : this.catalogMovies,
  );
  /** A disabled query keeps its cached entries, which turning browsing off must not show. */
  readonly catalogEntries = $derived(this.catalog.browsable ? (this.catalogQuery.data ?? []) : []);
  readonly groupView = $derived(uiState.collectionView === "groups");
  readonly currentGroup = $derived(this.groupView ? sidebarGroup() : null);
  /** The groups list sorts its groups; an open group its collections. */
  readonly sortScope = $derived<SortScope>(
    uiState.searchingTmdb
      ? "tmdb"
      : uiState.sidebarSource === "overturedb"
        ? "overturedb"
        : uiState.sidebarMode !== "collections"
          ? "library"
          : this.groupView && this.currentGroup === null
            ? "groups"
            : "collections",
  );
  readonly sortFields = $derived(
    sortMenu(this.sortScope, {
      inGroup: this.groupView,
      plex: settingsState.hasServerType("plex"),
    }),
  );
  /** The chosen sort; one this list does not offer, such as Group inside a group, gives way to its default. */
  readonly sort = $derived.by<SidebarSortPreference>(() => {
    const chosen = this.#sortByScope[this.sortScope][uiState.sidebarTab];
    return this.sortFields.some((entry) => entry.id === chosen.field)
      ? chosen
      : defaultSort(this.sortFields);
  });
  readonly tmdbFilterKeys = $derived(
    tmdbFilterKeysFor(uiState.sidebarSource, uiState.sidebarMode, this.catalog.enabled),
  );
  readonly catalogRows = $derived(
    filterCatalogEntries({
      entries: this.catalogEntries,
      filters: filterState.catalog,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: this.sort.field,
      sortDir: this.sort.dir,
    }),
  );
  readonly libraryItems = $derived.by(() =>
    uiState.sidebarTab === "movie" ? this.library().movies : this.library().shows,
  );
  readonly filteredItems = $derived(
    filterSidebarItems({
      items: this.libraryItems,
      filters: filterState.current,
      catalogEnabled: this.catalog.enabled,
      collectionMembers: this.#filteredCollection.ids,
      customFilter: this.#customFilter.predicate,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: this.sort.field,
      sortDir: this.sort.dir,
    }),
  );
  readonly filteredCollections = $derived(
    filterSidebarCollections({
      collections: this.collections,
      filters: filterState.current,
      catalogEnabled: this.catalog.enabled,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: this.sort.field,
      sortDir: this.sort.dir,
    }),
  );
  readonly collectionGroups = $derived(
    sortCollectionGroups(
      collectionGroupRows(
        sidebarGroupNames(this.groupsQuery.data ?? [], this.filteredCollections),
        this.filteredCollections,
      ),
      this.sort.field,
      this.sort.dir,
    ),
  );
  /** Grouped, the top level lists groups alone, as every collection is in one. */
  readonly visibleCollections = $derived.by(() => {
    if (!this.groupView) return this.filteredCollections;
    const group = this.currentGroup;
    return group === null
      ? []
      : this.filteredCollections.filter((row) => inCollectionGroup(row, group));
  });

  /**
   * What the list shows and in which order: its scope, sort, filters and
   * search. Auto-advance starts its walk again when it changes.
   */
  readonly view = $derived(
    JSON.stringify([
      uiState.sidebarSource,
      uiState.sidebarMode,
      uiState.sidebarTab,
      this.sortScope,
      this.sort,
      this.currentGroup,
      filterState.current,
      filterState.catalog,
      filterState.tmdb,
      uiState.searchQuery,
      uiState.searchField,
    ]),
  );

  /** The library titles listed, in order, which "Current sidebar items" operations act on. */
  readonly current = $derived.by(() => {
    const { loading, error } = this.library();
    return uiState.sidebarSource === "library" &&
      uiState.sidebarMode === "items" &&
      !uiState.searchingTmdb &&
      !loading &&
      !error
      ? { type: uiState.sidebarTab, itemIds: this.filteredItems.map((item) => item.id) }
      : null;
  });

  /** The collections listed, in order, which "Current sidebar items" operations act on. */
  readonly listedCollections = $derived(
    uiState.sidebarSource === "library" &&
      uiState.sidebarMode === "collections" &&
      this.collectionsQuery.isSuccess
      ? {
          type: uiState.sidebarTab,
          collectionIds: this.visibleCollections.map((row) => row.id),
        }
      : null,
  );

  /** The collections or catalog entries listed, in order, which auto-advance moves through. */
  readonly records = $derived<AdvanceRecord[] | null>(
    uiState.searchingTmdb
      ? null
      : uiState.sidebarSource === "overturedb"
        ? this.catalogRows.map(catalogRowRecord)
        : uiState.sidebarMode === "collections" && this.collectionsQuery.isSuccess
          ? this.visibleCollections.map(collectionRecord)
          : null,
  );

  /** Choose this list's sort, kept per tab. */
  setSort = (field: SidebarSortField, dir: SidebarSortDir) => {
    this.#sortByScope[this.sortScope][uiState.sidebarTab] = { field, dir };
    writeJson(`${SORT_KEYS[this.sortScope]}_${uiState.sidebarTab}`, { field, dir });
  };
}
