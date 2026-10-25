<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import type {
    CatalogEntryRow,
    CollectionRead,
    MediaItemRead,
  } from "../../generated/rest/types.gen";
  import {
    getPublicDatasetStatusOptions,
    listCollectionsOptions,
    listCatalogEntriesOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import {
    goToCatalogEntry,
    routedCatalogEntry,
    goToCollection,
    goToCollectionView,
    goToNewCollection,
    sidebarGroup,
    openSidebarGroup,
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
  import { collectionImageUrl, itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import type {
    SidebarSortPreference,
    SidebarSource,
    SidebarTab,
    SidebarSortDir as SortDir,
    SidebarSortField as SortField,
  } from "../utils/sidebarDomain";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import { readJson, writeJson } from "../utils/storage";
  import DataStatus from "./DataStatus.svelte";
  import SidebarControls from "./SidebarControls.svelte";
  import SidebarGroupBrowser from "./SidebarGroupBrowser.svelte";
  import SidebarGroupRow from "./SidebarGroupRow.svelte";
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
    enabled:
      settingsState.current.collections_supported &&
      uiState.sidebarSource === "library" &&
      (uiState.sidebarMode === "collections" || uiState.searchField === "tmdb"),
  }));
  let collections = $derived(collectionsQuery.data ?? []);

  const catalogMovies = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "movie" } }),
    enabled: datasetEnabled && uiState.sidebarSource === "overturedb",
  }));
  const catalogShows = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "show" } }),
    enabled: datasetEnabled && uiState.sidebarSource === "overturedb",
  }));
  const catalogCollections = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "collection" } }),
    enabled:
      datasetEnabled &&
      uiState.sidebarSource === "overturedb" &&
      uiState.sidebarMode === "collections",
  }));
  let catalogQuery = $derived(
    uiState.sidebarMode === "collections"
      ? catalogCollections
      : uiState.sidebarTab === "show"
        ? catalogShows
        : catalogMovies,
  );

  function sortStorageKey(source: SidebarSource, tab: SidebarTab) {
    return source === "library" ? `overture_sidebar_sort_${tab}` : `overture_catalog_sort_${tab}`;
  }

  function loadSortPreference(source: SidebarSource, tab: SidebarTab) {
    return sidebarDomain.normalizeSortPreference(
      readJson<unknown>(sortStorageKey(source, tab), null),
    );
  }

  /** Each source and tab remembers its own sort. */
  let sortBySource = $state<Record<SidebarSource, Record<SidebarTab, SidebarSortPreference>>>({
    library: {
      movie: loadSortPreference("library", "movie"),
      show: loadSortPreference("library", "show"),
    },
    overturedb: {
      movie: loadSortPreference("overturedb", "movie"),
      show: loadSortPreference("overturedb", "show"),
    },
  });
  let sort = $derived(sortBySource[uiState.sidebarSource][uiState.sidebarTab]);
  let catalogRows = $derived(
    sidebarDomain.filterCatalogEntries({
      entries: catalogQuery.data ?? [],
      filters: uiState.catalogFilters,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: sort.field,
      sortDir: sort.dir,
    }),
  );

  function setSort(field: SortField, dir: SortDir) {
    sortBySource[uiState.sidebarSource][uiState.sidebarTab] = { field, dir };
    writeJson(sortStorageKey(uiState.sidebarSource, uiState.sidebarTab), { field, dir });
  }

  // Whichever tab/mode combination is active is entirely driven by the URL
  // (see uiState.sidebarTab/sidebarMode). Reset the search box whenever that
  // combination changes, regardless of how the navigation happened (tab
  // button, mode toggle, browser back/forward, or a deep link).
  let section = $derived(`${uiState.sidebarSource}:${uiState.sidebarTab}:${uiState.sidebarMode}`);
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
  let scrollKey = $derived(
    `overture_sidebar_scroll:${section}${sidebarGroup() ? `:${sidebarGroup()}` : ""}`,
  );
  let savedScroll = $derived(readJson(scrollKey, 0, "session"));
  /** The pending write of the offset; scrolling writes at most every 200 ms. */
  let scrollSave: ReturnType<typeof setTimeout> | undefined;

  function rememberScroll(target: HTMLElement) {
    clearTimeout(scrollSave);
    const key = scrollKey;
    scrollSave = setTimeout(() => writeJson(key, target.scrollTop, "session"), 200);
  }

  // The TMDB field searches TMDB instead of filtering the library.
  let searchingTmdb = $derived(
    uiState.sidebarSource === "library" && uiState.searchField === "tmdb",
  );
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
      uiState.sidebarSource === "library" &&
      uiState.sidebarMode === "items" &&
      !searchingTmdb &&
      !loading &&
      !error
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

  let collectionGroups = $derived(
    [
      ...new Set(
        filteredCollections.flatMap((row) => (row.collection_group ? [row.collection_group] : [])),
      ),
    ].sort(),
  );
  let currentGroup = $derived(sidebarGroup());
  let visibleCollections = $derived(
    filteredCollections.filter((row) => row.collection_group === currentGroup),
  );

  $effect(() => {
    sidebarState.collections =
      uiState.sidebarSource === "library" &&
      uiState.sidebarMode === "collections" &&
      collectionsQuery.isSuccess
        ? { type: uiState.sidebarTab, collectionIds: visibleCollections.map((row) => row.id) }
        : null;
    return () => {
      sidebarState.collections = null;
    };
  });

  let itemsMessage = $derived(
    error || (filteredItems.length === 0 && !loading ? "No items found" : ""),
  );
  let collectionsMessage = $derived(
    collectionsQuery.isError && !collectionsQuery.data
      ? "Collections unavailable"
      : collectionsQuery.data &&
          visibleCollections.length === 0 &&
          (currentGroup !== null || collectionGroups.length === 0)
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
    artStatus={sidebarDomain.statusTone(collection.art_status, false)}
    themeStatus={sidebarDomain.statusTone(
      collection.theme_status,
      downloadState.isDownloadingCollection(collection.id),
    )}
    onSelect={() => openDetail(() => goToCollection(collection))}
    onOpenArt={() => openDetail(() => goToCollectionView(collection, "art"))}
    onOpenThemes={() => openDetail(() => goToCollectionView(collection, "themes"))}
  />
{/snippet}

{#snippet catalogRow(entry: CatalogEntryRow, index: number, style: string)}
  <SidebarRow
    {style}
    {index}
    catalogEntry={entry}
    active={routedCatalogEntry()?.entry_key === entry.entry_key}
    onSelect={() => openDetail(() => goToCatalogEntry(entry))}
    onOpenArt={() =>
      openDetail(() =>
        goToCatalogEntry(entry, { mode: "art", artSubTab: "poster", drillSeasonNum: null }),
      )}
    onOpenThemes={() =>
      openDetail(() =>
        goToCatalogEntry(entry, { mode: "themes", artSubTab: "poster", drillSeasonNum: null }),
      )}
  />
{/snippet}

{#snippet collectionGroupRow(group: string, _index: number, style: string)}
  <SidebarGroupRow
    title={group}
    count={filteredCollections.filter((row) => row.collection_group === group).length}
    {style}
    onselect={() => openSidebarGroup(group)}
  />
{/snippet}

<aside class="sidebar">
  <SidebarTabs
    {datasetEnabled}
    totalMovies={uiState.sidebarSource === "overturedb"
      ? (catalogMovies.data?.length ?? 0)
      : totalMovies}
    totalShows={uiState.sidebarSource === "overturedb"
      ? (catalogShows.data?.length ?? 0)
      : totalShows}
  />

  <SidebarControls
    source={uiState.sidebarSource}
    sidebarMode={uiState.sidebarMode}
    sidebarTab={uiState.sidebarTab}
    tmdbConfigured={settingsState.current.tmdb_configured}
    filtersOpen={uiState.openPopup === "filters"}
    hasActiveFilters={uiState.sidebarSource === "overturedb"
      ? sidebarDomain.CATALOG_FILTER_KEYS.some(
          (key) =>
            (key !== "seasonPosters" || uiState.sidebarTab === "show") &&
            uiState.catalogFilters[key] !== "all",
        )
      : sidebarDomain.hasVisibleActiveFilters(
          uiState.currentFilters,
          datasetEnabled,
          uiState.sidebarMode,
        )}
    filteredCount={uiState.sidebarSource === "overturedb"
      ? catalogRows.length
      : uiState.sidebarMode === "collections"
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

  {#if uiState.sidebarSource === "library" && uiState.sidebarMode === "collections" && settingsState.current.collections_supported}
    <div class="collection-actions">
      <button
        class="btn btn-ghost btn-sm"
        onclick={() => openDetail(() => goToNewCollection(uiState.sidebarTab))}
        >+ Create collection</button
      >
      <button class="btn btn-ghost btn-sm" onclick={() => uiState.openCollectionGroups()}
        >Manage groups</button
      >
    </div>
  {/if}
  {#if uiState.sidebarSource === "library" && uiState.sidebarMode === "collections" && collectionsQuery.isError}
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
      {#if uiState.sidebarSource === "overturedb"}
        {#if !datasetEnabled}
          <p class="text-muted">Enable OvertureDB to browse the catalog.</p>
        {:else}
          <DataStatus
            label="catalog"
            error={catalogQuery.error}
            loading={catalogQuery.isFetching}
            hasData={catalogQuery.data !== undefined}
            onretry={() => catalogQuery.refetch()}
          />
          <SidebarList
            rows={catalogRows}
            loading={catalogQuery.isPending}
            message={catalogQuery.data && catalogRows.length === 0
              ? "No catalog entries found"
              : ""}
            scrollOffset={savedScroll}
            getKey={(entry) => entry.entry_key}
            posterUrl={remotePosterUrl}
            entry={catalogRow}
          />
        {/if}
      {:else if searchingTmdb}
        <TmdbSearchResults
          query={uiState.searchQuery}
          tab={uiState.sidebarTab}
          {libraryItems}
          {libraryRow}
          {collections}
          collectionsOnly={uiState.sidebarMode === "collections"}
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
        <SidebarGroupBrowser
          groups={collectionGroups}
          rows={visibleCollections}
          selected={currentGroup}
          groupTitle={(group) => group}
          groupKey={(group) => group}
          groupPoster={() => null}
          groupEntry={collectionGroupRow}
          entry={collectionRow}
          onback={() => openSidebarGroup(null)}
          loading={collectionsQuery.isFetching && !collectionsQuery.data}
          message={collectionsMessage}
          scrollOffset={savedScroll}
          getKey={(collection) => collection.id}
          posterUrl={(collection) => collectionImageUrl(collection.thumb_url)}
        />
      {/if}
    {/key}
  </div>
</aside>

<style>
  .collection-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-2);
  }
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
