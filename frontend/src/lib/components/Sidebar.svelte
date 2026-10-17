<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import { createQuery } from "@tanstack/svelte-query";
  import type { CollectionRead, MediaItemRead } from "../../generated/rest/types.gen";
  import { listCollectionsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import {
    goToCollection,
    goToCollectionsList,
    goToItem,
    goToItemArt,
    goToItemThemes,
    goToLibrary,
  } from "../router/routes";
  import { collectionState } from "../stores/collectionState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { publicDatasetState } from "../stores/publicDatasetState.svelte";
  import { selectedState } from "../stores/selectedState.svelte";
  import { sidebarState } from "../stores/sidebarState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { collectionImageUrl, itemArtDisplayUrl } from "../utils/artDisplay";
  import { preloadImages } from "../utils/imagePreload";
  import type {
    SidebarTab,
    SidebarSortDir as SortDir,
    SidebarSortField as SortField,
  } from "../utils/sidebarDomain";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import { readJson, writeJson } from "../utils/storage";
  import DataStatus from "./DataStatus.svelte";
  import SidebarControls from "./SidebarControls.svelte";
  import SidebarRow from "./SidebarRow.svelte";
  import TmdbSearchResults from "./TmdbSearchResults.svelte";
  import VirtualList from "./VirtualList.svelte";

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

  function sortStorageKey(tab: SidebarTab) {
    return `overture_sidebar_sort_${tab}`;
  }

  function loadSortPreference(tab: SidebarTab) {
    return sidebarDomain.normalizeSortPreference(readJson<unknown>(sortStorageKey(tab), null));
  }

  function saveSortPreference(tab: SidebarTab, field: SortField, dir: SortDir) {
    writeJson(sortStorageKey(tab), { field, dir });
  }

  const collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "collections",
  }));
  let collections = $derived(collectionsQuery.data ?? []);
  let loadingCollections = $derived(collectionsQuery.isFetching);

  let initialSort = loadSortPreference(uiState.sidebarTab);
  let sortField = $state<SortField>(initialSort.field);
  let sortDir = $state<SortDir>(initialSort.dir);
  let loadedSortTab = $state<SidebarTab>(uiState.sidebarTab);
  $effect(() => {
    const tab = uiState.sidebarTab;
    if (tab === loadedSortTab) return;
    loadedSortTab = tab;
    const preference = loadSortPreference(tab);
    sortField = preference.field;
    sortDir = preference.dir;
  });

  function setSort(field: SortField, dir: SortDir) {
    sortField = field;
    sortDir = dir;
    saveSortPreference(uiState.sidebarTab, field, dir);
  }

  function resetSearchControls() {
    uiState.searchQuery = "";
    uiState.searchField = "title";
  }

  // Whichever tab/mode combination is active is entirely driven by the URL
  // (see uiState.sidebarTab/sidebarMode). Reset the search box whenever that
  // combination changes, regardless of how the navigation happened (tab
  // button, mode toggle, browser back/forward, or a deep link).
  let loadedSection = $state(`${uiState.sidebarTab}:${uiState.sidebarMode}`);
  $effect(() => {
    const section = `${uiState.sidebarTab}:${uiState.sidebarMode}`;
    if (section === loadedSection) return;
    loadedSection = section;
    resetSearchControls();
  });

  function switchSidebarTab(tab: SidebarTab) {
    // A top-level tab switch is a request to browse that library. Clear the
    // old detail state immediately and keep the browser surface visible on
    // mobile while the matching route settles.
    selectedState.selectItem(null);
    collectionState.selectCollection(null);
    uiState.mobileShowDetail = false;
    goToLibrary(tab);
  }

  function switchSidebarMode(mode: "items" | "collections") {
    if (mode === "collections") {
      selectedState.selectItem(null);
      goToCollectionsList(uiState.sidebarTab);
    } else {
      collectionState.selectCollection(null);
      goToLibrary(uiState.sidebarTab);
    }
  }

  function openDetail(navigate: () => void) {
    uiState.mobileShowDetail = true;
    navigate();
  }

  /** Each tab and mode keeps its own place in the list for the session. */
  let scrollKey = $derived(`overture_sidebar_scroll:${uiState.sidebarTab}:${uiState.sidebarMode}`);
  let savedScroll = $derived(readJson(scrollKey, 0, "session"));
  /** The pending write of the offset; scrolling writes at most every 200 ms. */
  let scrollSave: ReturnType<typeof setTimeout> | undefined;

  function rememberScroll(target: HTMLElement) {
    clearTimeout(scrollSave);
    const key = scrollKey;
    scrollSave = setTimeout(() => writeJson(key, target.scrollTop, "session"), 200);
  }

  function checkVisibleActiveFilters() {
    return sidebarDomain.hasVisibleActiveFilters(
      uiState.currentFilters,
      publicDatasetState.enabled,
      uiState.sidebarMode,
    );
  }

  // The TMDB field searches TMDB instead of filtering the library.
  let searchingTmdb = $derived(uiState.sidebarMode === "items" && uiState.searchField === "tmdb");

  let filteredItems = $derived(
    sidebarDomain.filterSidebarItems({
      items: uiState.sidebarTab === "movie" ? movies : shows,
      filters: uiState.currentFilters,
      publicDatasetEnabled: publicDatasetState.enabled,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField,
      sortDir,
    }),
  );

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

  /** How long scrolling must rest before posters around the viewport are fetched. */
  const PRELOAD_IDLE_MS = 150;
  let visibleRange = $state<[number, number]>([0, 0]);
  function setVisibleRange(first: number, end: number) {
    visibleRange = [first, end];
  }
  $effect(() => {
    const [first, end] = visibleRange;
    const posters =
      uiState.sidebarMode === "collections"
        ? sidebarDomain
            .preloadRowIndexes(first, end, filteredCollections.length)
            .map((index) => collectionImageUrl(filteredCollections[index]?.thumb_url))
        : sidebarDomain
            .preloadRowIndexes(first, end, filteredItems.length)
            .map((index) => itemArtDisplayUrl(filteredItems[index] ?? null, "poster"));
    const timer = setTimeout(() => preloadImages(posters, "sidebar"), PRELOAD_IDLE_MS);
    return () => clearTimeout(timer);
  });

  function getCollectionThemeStatus(coll: CollectionRead) {
    return sidebarDomain.statusTone(
      coll.theme_status,
      downloadState.isDownloadingCollection(coll.id),
    );
  }

  function getArtStatus(item: MediaItemRead) {
    return sidebarDomain.statusTone(
      item.art_status,
      downloadState.isDownloadingType(item.id, "art"),
    );
  }

  function getThemeStatus(item: MediaItemRead) {
    return sidebarDomain.statusTone(
      item.theme_status,
      downloadState.isDownloadingType(item.id, "theme"),
    );
  }
</script>

{#snippet libraryRow(item: MediaItemRead, index: number, style: string)}
  <SidebarRow
    {style}
    {index}
    active={selectedState.item?.id === item.id}
    {item}
    artStatus={getArtStatus(item)}
    themeStatus={getThemeStatus(item)}
    onSelect={() => openDetail(() => goToItem(item))}
    onOpenArt={() => openDetail(() => goToItemArt(item, "poster"))}
    onOpenThemes={() => openDetail(() => goToItemThemes(item))}
  />
{/snippet}

<aside class="sidebar">
  <div class="sidebar-tabs">
    <button
      type="button"
      class="sidebar-tab"
      class:active={uiState.sidebarTab === "movie"}
      aria-pressed={uiState.sidebarTab === "movie"}
      onclick={() => switchSidebarTab("movie")}
    >
      <Clapperboard size={16} />
      <span>Movies</span>
      <span class="tab-count">{totalMovies}</span>
    </button>
    <button
      type="button"
      class="sidebar-tab"
      class:active={uiState.sidebarTab === "show"}
      aria-pressed={uiState.sidebarTab === "show"}
      onclick={() => switchSidebarTab("show")}
    >
      <MonitorPlay size={16} />
      <span>Shows</span>
      <span class="tab-count">{totalShows}</span>
    </button>
  </div>

  <!-- Mode Toggle -->
  {#if settingsState.current.media_server === "plex" && settingsState.current.plex_collections_enabled}
    <div class="sidebar-mode-toggle">
      <button
        type="button"
        class="mode-btn"
        class:active={uiState.sidebarMode === "items"}
        aria-pressed={uiState.sidebarMode === "items"}
        onclick={() => switchSidebarMode("items")}>Items</button
      >
      <button
        type="button"
        class="mode-btn"
        class:active={uiState.sidebarMode === "collections"}
        aria-pressed={uiState.sidebarMode === "collections"}
        onclick={() => switchSidebarMode("collections")}>Collections</button
      >
    </div>
  {/if}

  <SidebarControls
    sidebarMode={uiState.sidebarMode}
    sidebarTab={uiState.sidebarTab}
    tmdbConfigured={settingsState.current.tmdb_configured}
    filtersOpen={uiState.openPopup === "filters"}
    hasActiveFilters={checkVisibleActiveFilters()}
    filteredCount={uiState.sidebarMode === "collections"
      ? filteredCollections.length
      : filteredItems.length}
    searchQuery={uiState.searchQuery}
    searchField={uiState.searchField}
    {sortField}
    {sortDir}
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
    onscrollcapture={(e) => {
      if (e.target instanceof HTMLElement) rememberScroll(e.target);
    }}
  >
    {#key scrollKey}
      {#if searchingTmdb}
        <TmdbSearchResults
          query={uiState.searchQuery}
          tab={uiState.sidebarTab}
          libraryItems={uiState.sidebarTab === "movie" ? movies : shows}
          {libraryRow}
          onOpen={openDetail}
        />
      {:else if uiState.sidebarMode === "items"}
        {#if loading && filteredItems.length === 0}
          <div class="sidebar-loader">
            <LoaderCircle size={24} class="animate-spin" />
          </div>
        {:else if error}
          <div class="sidebar-empty">{error}</div>
        {:else if filteredItems.length === 0}
          <div class="sidebar-empty">No items found</div>
        {:else}
          <VirtualList
            width="100%"
            maxHeight="100%"
            itemCount={filteredItems.length}
            itemSize={88}
            scrollOffset={savedScroll}
            overscanCount={sidebarDomain.SIDEBAR_OVERSCAN_ROWS}
            onVisibleRangeChange={setVisibleRange}
            getKey={(index) => filteredItems[index]?.id ?? index}
          >
            {#snippet row(index: number, style: string)}
              {@const item = filteredItems[index]}
              {#if item}
                {@render libraryRow(item, index, style)}
              {/if}
            {/snippet}
          </VirtualList>
        {/if}
      {:else if loadingCollections && !collectionsQuery.data}
        <div class="sidebar-loader">
          <LoaderCircle size={24} class="animate-spin" />
        </div>
      {:else if collectionsQuery.isError && !collectionsQuery.data}
        <div class="sidebar-empty">Collections unavailable</div>
      {:else if filteredCollections.length === 0}
        <div class="sidebar-empty">No collections found</div>
      {:else}
        <VirtualList
          width="100%"
          maxHeight="100%"
          itemCount={filteredCollections.length}
          itemSize={88}
          scrollOffset={savedScroll}
          overscanCount={sidebarDomain.SIDEBAR_OVERSCAN_ROWS}
          onVisibleRangeChange={setVisibleRange}
          getKey={(index) => filteredCollections[index]?.id ?? index}
        >
          {#snippet row(index: number, style: string)}
            {@const coll = filteredCollections[index]}
            {#if coll}
              <SidebarRow
                {style}
                {index}
                active={collectionState.selectedCollection?.id === coll.id}
                collection={coll}
                themeStatus={getCollectionThemeStatus(coll)}
                onSelect={() => openDetail(() => goToCollection(coll))}
              />
            {/if}
          {/snippet}
        </VirtualList>
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

  .sidebar-tabs {
    display: flex;
    border-bottom: var(--border-subtle);
  }

  .sidebar-tab {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-tertiary);
    border-bottom: 2px solid transparent;
  }

  .sidebar-tab:hover {
    color: var(--text-secondary);
    background: var(--bg-secondary);
  }

  .sidebar-tab.active {
    color: var(--text-primary);
    border-bottom-color: var(--accent);
  }

  .tab-count {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    background: var(--bg-tertiary);
    padding: 1px 6px;
    border-radius: var(--radius-full);
    color: var(--text-secondary);
  }

  .sidebar-list {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .sidebar-loader,
  .sidebar-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-10);
    color: var(--text-tertiary);
    font-size: var(--text-sm);
  }

  .sidebar-loader :global(.animate-spin) {
    animation: spin 1s linear infinite;
  }

  .sidebar-mode-toggle {
    display: flex;
    background: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    padding: 2px;
  }

  .mode-btn {
    flex: 1;
    border: none;
    background: transparent;
    color: var(--text-tertiary);
    font-size: var(--text-xs);
    font-weight: 500;
    padding: var(--space-1) 0;
    border-radius: calc(var(--radius-sm) - 2px);
    cursor: pointer;
  }

  .mode-btn:hover {
    color: var(--text-primary);
  }

  .mode-btn.active {
    background: var(--bg-primary);
    color: var(--text-primary);
    box-shadow: var(--shadow-sm);
  }

  @media (max-width: 768px), (max-height: 500px) and (pointer: coarse) {
    .sidebar {
      width: 100%;
      min-width: 0;
    }
  }
</style>
