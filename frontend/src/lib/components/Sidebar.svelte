<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import type { CollectionRead, MediaItemRead } from "../../generated/rest/types.gen";
  import {
    getPublicDatasetStatusOptions,
    listCollectionsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import {
    goToCollection,
    goToItem,
    goToItemArt,
    goToItemThemes,
    routedCollectionId,
    routedItemId,
  } from "../router/routes";
  import { downloadState } from "../stores/downloadState.svelte";
  import { sidebarState } from "../stores/sidebarState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { collectionImageUrl, itemArtDisplayUrl } from "../utils/artDisplay";
  import type {
    SidebarSortPreference,
    SidebarTab,
    SidebarSortDir as SortDir,
    SidebarSortField as SortField,
  } from "../utils/sidebarDomain";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import { readJson, writeJson } from "../utils/storage";
  import DataStatus from "./DataStatus.svelte";
  import SidebarControls from "./SidebarControls.svelte";
  import SidebarList from "./SidebarList.svelte";
  import SidebarRow from "./SidebarRow.svelte";
  import SidebarTabs from "./SidebarTabs.svelte";
  import TmdbSearchResults from "./TmdbSearchResults.svelte";

  let {
    loading = false,
    error = "",
    movies = [],
    totalMovies = 0,
    totalShows = 0,
    shows = [],
  }: {
    loading?: boolean;
    error?: string;
    movies?: MediaItemRead[];
    totalMovies?: number;
    totalShows?: number;
    shows?: MediaItemRead[];
  } = $props();

  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());
  let datasetEnabled = $derived(datasetQuery.data?.enabled ?? false);

  const collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "collections",
  }));
  let collections = $derived(collectionsQuery.data ?? []);

  function sortStorageKey(tab: SidebarTab) {
    return `overture_sidebar_sort_${tab}`;
  }

  function loadSortPreference(tab: SidebarTab) {
    return sidebarDomain.normalizeSortPreference(readJson<unknown>(sortStorageKey(tab), null));
  }

  /** Each tab keeps its own sort, which the browser remembers. */
  let sortByTab = $state<Record<SidebarTab, SidebarSortPreference>>({
    movie: loadSortPreference("movie"),
    show: loadSortPreference("show"),
  });
  let sort = $derived(sortByTab[uiState.sidebarTab]);

  function setSort(field: SortField, dir: SortDir) {
    sortByTab[uiState.sidebarTab] = { field, dir };
    writeJson(sortStorageKey(uiState.sidebarTab), { field, dir });
  }

  // Whichever tab/mode combination is active is entirely driven by the URL
  // (see uiState.sidebarTab/sidebarMode). Reset the search box whenever that
  // combination changes, regardless of how the navigation happened (tab
  // button, mode toggle, browser back/forward, or a deep link).
  let section = $derived(`${uiState.sidebarTab}:${uiState.sidebarMode}`);
  let searchedSection = untrack(() => section);
  $effect(() => {
    if (section === searchedSection) return;
    searchedSection = section;
    uiState.searchQuery = "";
    uiState.searchField = "title";
  });

  function openDetail(navigate: () => void) {
    uiState.mobileShowDetail = true;
    navigate();
  }

  /** Each tab and mode keeps its own place in the list for the session. */
  let scrollKey = $derived(`overture_sidebar_scroll:${section}`);
  let savedScroll = $derived(readJson(scrollKey, 0, "session"));
  /** The pending write of the offset; scrolling writes at most every 200 ms. */
  let scrollSave: ReturnType<typeof setTimeout> | undefined;

  function rememberScroll(target: HTMLElement) {
    clearTimeout(scrollSave);
    const key = scrollKey;
    scrollSave = setTimeout(() => writeJson(key, target.scrollTop, "session"), 200);
  }

  // The TMDB field searches TMDB instead of filtering the library.
  let searchingTmdb = $derived(uiState.sidebarMode === "items" && uiState.searchField === "tmdb");
  let libraryItems = $derived(uiState.sidebarTab === "movie" ? movies : shows);

  let filteredItems = $derived(
    sidebarDomain.filterSidebarItems({
      items: libraryItems,
      filters: uiState.currentFilters,
      publicDatasetEnabled: datasetEnabled,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: sort.field,
      sortDir: sort.dir,
    }),
  );

  // Auto-advance follows the order the user sees.
  $effect(() => {
    sidebarState.current =
      uiState.sidebarMode === "items" && !searchingTmdb && !loading && !error
        ? { type: uiState.sidebarTab, itemIds: filteredItems.map((item) => item.id) }
        : null;
    return () => {
      sidebarState.current = null;
    };
  });

  let filteredCollections = $derived(
    sidebarDomain.filterSidebarCollections({
      collections,
      filters: uiState.currentFilters,
      searchQuery: uiState.searchQuery,
    }),
  );

  let itemsMessage = $derived(
    error || (filteredItems.length === 0 && !loading ? "No items found" : ""),
  );
  let collectionsMessage = $derived(
    collectionsQuery.isError && !collectionsQuery.data
      ? "Collections unavailable"
      : collectionsQuery.data && filteredCollections.length === 0
        ? "No collections found"
        : "",
  );
</script>

{#snippet libraryRow(item: MediaItemRead, index: number, style: string)}
  <SidebarRow
    {style}
    {index}
    active={routedItemId() === item.id}
    {item}
    artStatus={sidebarDomain.statusTone(
      item.art_status,
      downloadState.isDownloadingType(item.id, "art"),
    )}
    themeStatus={sidebarDomain.statusTone(
      item.theme_status,
      downloadState.isDownloadingType(item.id, "theme"),
    )}
    onSelect={() => openDetail(() => void goToItem(item))}
    onOpenArt={() => openDetail(() => goToItemArt(item, "poster"))}
    onOpenThemes={() => openDetail(() => goToItemThemes(item))}
  />
{/snippet}

{#snippet collectionRow(collection: CollectionRead, index: number, style: string)}
  <SidebarRow
    {style}
    {index}
    active={routedCollectionId() === collection.id}
    {collection}
    themeStatus={sidebarDomain.statusTone(
      collection.theme_status,
      downloadState.isDownloadingCollection(collection.id),
    )}
    onSelect={() => openDetail(() => goToCollection(collection))}
  />
{/snippet}

<aside class="sidebar">
  <SidebarTabs {totalMovies} {totalShows} />

  <SidebarControls
    sidebarMode={uiState.sidebarMode}
    sidebarTab={uiState.sidebarTab}
    tmdbConfigured={settingsState.current.tmdb_configured}
    filtersOpen={uiState.openPopup === "filters"}
    hasActiveFilters={sidebarDomain.hasVisibleActiveFilters(
      uiState.currentFilters,
      datasetEnabled,
      uiState.sidebarMode,
    )}
    filteredCount={uiState.sidebarMode === "collections"
      ? filteredCollections.length
      : filteredItems.length}
    searchQuery={uiState.searchQuery}
    searchField={uiState.searchField}
    sortField={sort.field}
    sortDir={sort.dir}
    onOpenFilters={() => uiState.openPopupByName("filters")}
    onSearchQueryChange={(value) => {
      uiState.searchQuery = value;
    }}
    onSearchFieldChange={(field) => {
      uiState.searchField = field;
      uiState.searchQuery = "";
    }}
    onSetSort={setSort}
  />

  {#if uiState.sidebarMode === "collections" && collectionsQuery.isError}
    <DataStatus
      label="collections"
      error={collectionsQuery.error}
      hasData={collectionsQuery.data !== undefined}
      loading={collectionsQuery.isFetching}
      onretry={() => collectionsQuery.refetch()}
    />
  {/if}

  <div
    class="sidebar-list"
    onscrollcapture={(event) => {
      if (event.target instanceof HTMLElement) rememberScroll(event.target);
    }}
  >
    {#key scrollKey}
      {#if searchingTmdb}
        <TmdbSearchResults
          query={uiState.searchQuery}
          tab={uiState.sidebarTab}
          {libraryItems}
          {libraryRow}
          onOpen={openDetail}
        />
      {:else if uiState.sidebarMode === "items"}
        <SidebarList
          rows={filteredItems}
          loading={loading && filteredItems.length === 0}
          message={itemsMessage}
          scrollOffset={savedScroll}
          getKey={(item) => item.id}
          posterUrl={(item) => itemArtDisplayUrl(item, "poster")}
          entry={libraryRow}
        />
      {:else}
        <SidebarList
          rows={filteredCollections}
          loading={collectionsQuery.isFetching && !collectionsQuery.data}
          message={collectionsMessage}
          scrollOffset={savedScroll}
          getKey={(collection) => collection.id}
          posterUrl={(collection) => collectionImageUrl(collection.thumb_url)}
          entry={collectionRow}
        />
      {/if}
    {/key}
  </div>
</aside>

<style>
  .sidebar {
    width: var(--sidebar-width);
    min-width: var(--sidebar-width);
    display: flex;
    flex-direction: column;
    background: var(--bg-primary);
    border-right: var(--border-subtle);
    overflow: hidden;
  }

  .sidebar-list {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  @media (max-width: 768px), (max-height: 500px) and (pointer: coarse) {
    .sidebar {
      width: 100%;
      min-width: 0;
    }
  }
</style>
