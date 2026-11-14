<script lang="ts">
  import Folders from "@lucide/svelte/icons/folders";
  import LayersPlus from "@lucide/svelte/icons/layers-plus";
  import { createQuery } from "@tanstack/svelte-query";
  import type {
    CatalogEntryRow,
    CollectionRead,
    MediaItemRead,
  } from "../../generated/rest/types.gen";
  import {
    listCollectionGroupsOptions,
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
  import { defaultFilters, uiState } from "../stores/uiState.svelte";
  import { CatalogBrowsing } from "../utils/catalogBrowsing.svelte";
  import { CollectionMembers } from "../utils/collectionMembers.svelte";
  import { collectionArtDisplayUrl, itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import type {
    SidebarSortPreference,
    SortScope,
    SidebarTab,
    SidebarSortDir as SortDir,
    SidebarSortField as SortField,
  } from "../utils/sidebarDomain";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import { UNMANAGED_GROUP, UNGROUPED_GROUP } from "../../generated/settings";
  import { readJson, writeJson } from "../utils/storage";
  import DataStatus from "./DataStatus.svelte";
  import SidebarControls from "./SidebarControls.svelte";
  import SidebarGroupBrowser from "./SidebarGroupBrowser.svelte";
  import SidebarGroupRow from "./SidebarGroupRow.svelte";
  import SidebarList from "./SidebarList.svelte";
  import SidebarRow from "./SidebarRow.svelte";
  import SidebarTabs from "./SidebarTabs.svelte";
  import TmdbSearchResults from "./TmdbSearchResults.svelte";
  import { catalogRowRecord, collectionRecord } from "../utils/recordAdvance";

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

  const catalog = new CatalogBrowsing();

  const collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions(),
    enabled: settingsState.current.collections_supported && uiState.sidebarSource === "library",
  }));
  let collections = $derived(collectionsQuery.data ?? []);
  const groupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions(),
    enabled: settingsState.current.collections_supported && uiState.sidebarSource === "library",
  }));

  const catalogMovies = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "movie" } }),
    enabled: catalog.browsable && uiState.sidebarSource === "overturedb",
  }));
  const catalogShows = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "show" } }),
    enabled: catalog.browsable && uiState.sidebarSource === "overturedb",
  }));
  const catalogCollections = createQuery(() => ({
    ...listCatalogEntriesOptions({ query: { media_type: "collection" } }),
    enabled: catalog.browsable && uiState.sidebarSource === "overturedb",
  }));
  let catalogQuery = $derived(
    uiState.sidebarMode === "collections"
      ? catalogCollections
      : uiState.sidebarTab === "show"
        ? catalogShows
        : catalogMovies,
  );
  // A disabled query keeps its cached entries, which turning browsing off must not show.
  let catalogEntries = $derived(catalog.browsable ? (catalogQuery.data ?? []) : []);

  const SORT_KEYS: Record<SortScope, string> = {
    library: "overture_sidebar_sort",
    collections: "overture_collection_sort",
    groups: "overture_group_sort",
    overturedb: "overture_catalog_sort",
  };

  function loadSortPreference(scope: SortScope, tab: SidebarTab) {
    return sidebarDomain.normalizeSortPreference(
      readJson<unknown>(`${SORT_KEYS[scope]}_${tab}`, null),
      scope,
    );
  }

  /** Items, collections, groups and the catalog each remember their sort per tab. */
  let sortByScope = $state<Record<SortScope, Record<SidebarTab, SidebarSortPreference>>>({
    library: {
      movie: loadSortPreference("library", "movie"),
      show: loadSortPreference("library", "show"),
    },
    collections: {
      movie: loadSortPreference("collections", "movie"),
      show: loadSortPreference("collections", "show"),
    },
    groups: {
      movie: loadSortPreference("groups", "movie"),
      show: loadSortPreference("groups", "show"),
    },
    overturedb: {
      movie: loadSortPreference("overturedb", "movie"),
      show: loadSortPreference("overturedb", "show"),
    },
  });
  let groupView = $derived(uiState.collectionView === "groups");
  let currentGroup = $derived(groupView ? sidebarGroup() : null);
  /** The groups list sorts its groups; an open group its collections. */
  let sortScope = $derived<SortScope>(
    uiState.sidebarSource === "overturedb"
      ? "overturedb"
      : uiState.sidebarMode !== "collections"
        ? "library"
        : groupView && currentGroup === null
          ? "groups"
          : "collections",
  );
  let sortFields = $derived(
    sidebarDomain.sortMenu(sortScope, {
      inGroup: groupView,
      plex: settingsState.current.media_server === "plex",
    }),
  );
  let chosenSort = $derived(sortByScope[sortScope][uiState.sidebarTab]);
  // A saved sort this list does not offer, such as Group inside a group, falls back to Title.
  let sort = $derived<SidebarSortPreference>(
    sortFields.some((entry) => entry.id === chosenSort.field)
      ? chosenSort
      : { field: "title", dir: "asc" },
  );
  let catalogRows = $derived(
    sidebarDomain.filterCatalogEntries({
      entries: catalogEntries,
      filters: uiState.catalogFilters,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: sort.field,
      sortDir: sort.dir,
    }),
  );

  function setSort(field: SortField, dir: SortDir) {
    sortByScope[sortScope][uiState.sidebarTab] = { field, dir };
    writeJson(`${SORT_KEYS[sortScope]}_${uiState.sidebarTab}`, { field, dir });
  }

  let section = $derived(uiState.sidebarSection);
  $effect(() => uiState.followSection());

  function openDetail(navigate: () => void) {
    uiState.mobileShowDetail = true;
    navigate();
  }

  /** Each tab and mode keeps its own place in the list for the session. */
  let scrollKey = $derived.by(() => {
    if (uiState.sidebarMode !== "collections") return `overture_sidebar_scroll:${section}`;
    const group = uiState.collectionView === "groups" ? sidebarGroup() : null;
    return `overture_sidebar_scroll:${section}:${uiState.collectionView}${group ? `:${group}` : ""}`;
  });
  let savedScroll = $derived(readJson(scrollKey, 0, "session"));
  /** The pending write of the offset; scrolling writes at most every 200 ms. */
  let scrollSave: ReturnType<typeof setTimeout> | undefined;

  function rememberScroll(target: HTMLElement) {
    clearTimeout(scrollSave);
    const key = scrollKey;
    scrollSave = setTimeout(() => writeJson(key, target.scrollTop, "session"), 200);
  }

  let searchingTmdb = $derived(uiState.searchField === "tmdb");
  let libraryItems = $derived(uiState.sidebarTab === "movie" ? movies : shows);

  const filteredCollection = new CollectionMembers(() =>
    uiState.sidebarMode === "items" ? uiState.currentFilters.collectionId : null,
  );
  let filteredItems = $derived(
    sidebarDomain.filterSidebarItems({
      items: libraryItems,
      filters: uiState.currentFilters,
      catalogEnabled: catalog.enabled,
      collectionMembers: filteredCollection.ids,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: sort.field,
      sortDir: sort.dir,
    }),
  );

  $effect(() => {
    sidebarState.view = JSON.stringify([
      uiState.sidebarSource,
      uiState.sidebarMode,
      uiState.sidebarTab,
      sortScope,
      sort,
      currentGroup,
      uiState.currentFilters,
      uiState.catalogFilters,
      uiState.searchQuery,
      uiState.searchField,
    ]);
    return () => {
      sidebarState.view = null;
    };
  });

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
      catalogEnabled: catalog.enabled,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
      sortField: sort.field,
      sortDir: sort.dir,
    }),
  );

  let collectionGroups = $derived(
    sidebarDomain.sortCollectionGroups(
      sidebarDomain.collectionGroupRows(
        sidebarDomain.collectionGroupNames(groupsQuery.data ?? [], filteredCollections),
        filteredCollections,
      ),
      sort.field,
      sort.dir,
    ),
  );
  let visibleCollections = $derived(
    groupView
      ? filteredCollections.filter((row) => sidebarDomain.inCollectionGroup(row, currentGroup))
      : filteredCollections,
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

  // Auto-advance moves through collections and catalog entries as they are shown.
  $effect(() => {
    sidebarState.records = searchingTmdb
      ? null
      : uiState.sidebarSource === "overturedb"
        ? catalogRows.map(catalogRowRecord)
        : uiState.sidebarMode === "collections" && collectionsQuery.isSuccess
          ? visibleCollections.map(collectionRecord)
          : null;
    return () => {
      sidebarState.records = null;
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
          (!groupView || currentGroup !== null || collectionGroups.length === 0)
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

{#snippet collectionGroupRow(group: sidebarDomain.CollectionGroupRow, _index: number, style: string)}
  <SidebarGroupRow
    title={group.title}
    count={group.collections}
    {style}
    locked={group.title === UNMANAGED_GROUP || group.title === UNGROUPED_GROUP}
    onselect={() => openSidebarGroup(group.title)}
  />
{/snippet}

<aside class={["sidebar", { "detail-shown": uiState.mobileShowDetail }]}>
  <SidebarTabs
    totalMovies={uiState.sidebarSource === "overturedb"
      ? (catalogMovies.data?.length ?? 0)
      : totalMovies}
    totalShows={uiState.sidebarSource === "overturedb"
      ? (catalogShows.data?.length ?? 0)
      : totalShows}
    totalCollections={uiState.sidebarSource === "overturedb"
      ? (catalogCollections.data?.length ?? 0)
      : groupView
        ? sidebarDomain.collectionGroupNames(groupsQuery.data ?? [], collections).length
        : collections.length}
  />

  <SidebarControls
    {section}
    searchGroups={sidebarDomain.searchFieldGroups(
      uiState.sidebarSource,
      uiState.sidebarMode,
      uiState.sidebarTab,
      settingsState.current.tmdb_configured,
    )}
    placeholder={sidebarDomain.searchPlaceholder(
      uiState.sidebarMode,
      uiState.sidebarTab,
      uiState.searchField,
      uiState.sidebarSource === "overturedb"
        ? catalogRows.length
        : uiState.sidebarMode === "collections"
          ? filteredCollections.length
          : filteredItems.length,
    )}
    sortFields={searchingTmdb ? [] : sortFields}
    filtersOpen={uiState.openPopup === "filters"}
    activeFilters={uiState.sidebarSource === "overturedb"
      ? sidebarDomain.CATALOG_FILTER_KEYS.filter(
          (key) =>
            (key !== "seasonPosters" || uiState.sidebarTab === "show") &&
            uiState.catalogFilters[key] !== "all",
        ).length
      : sidebarDomain.activeFilterCount(
          uiState.currentFilters,
          catalog.enabled,
          uiState.sidebarMode,
        )}
    onResetFilters={() => {
      if (uiState.sidebarSource === "overturedb")
        uiState.catalogFilters = sidebarDomain.defaultCatalogFilters();
      else uiState.setFilters(defaultFilters());
    }}
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
        type="button"
        class="btn btn-secondary btn-sm"
        onclick={() => openDetail(() => goToNewCollection())}
        ><LayersPlus size={14} />Create collection</button
      >
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        onclick={() => uiState.openCollectionGroups()}><Folders size={14} />Manage groups</button
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
        {#if searchingTmdb}
          <TmdbSearchResults
            query={uiState.searchQuery}
            tab={uiState.sidebarTab}
            libraryItems={[]}
            {libraryRow}
            {catalogEntries}
            {catalogRow}
            collectionsOnly={uiState.sidebarMode === "collections"}
            onOpen={openDetail}
          />
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
      {:else if !groupView}
        <SidebarList
          rows={visibleCollections}
          loading={collectionsQuery.isFetching && !collectionsQuery.data}
          message={collectionsMessage}
          scrollOffset={savedScroll}
          getKey={(collection) => collection.id}
          posterUrl={(collection) => collectionArtDisplayUrl(collection, "poster")}
          entry={collectionRow}
        />
      {:else}
        <SidebarGroupBrowser
          groups={collectionGroups}
          rows={visibleCollections}
          selected={currentGroup === null ? null : { title: currentGroup }}
          groupTitle={(group) => group.title}
          groupKey={(group) => group.title}
          groupPoster={() => null}
          groupEntry={collectionGroupRow}
          entry={collectionRow}
          onback={() => openSidebarGroup(null)}
          loading={collectionsQuery.isFetching && !collectionsQuery.data}
          message={collectionsMessage}
          scrollOffset={savedScroll}
          getKey={(collection) => collection.id}
          posterUrl={(collection) => collectionArtDisplayUrl(collection, "poster")}
        />
      {/if}
    {/key}
  </div>
</aside>

<style>
  .collection-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-2);
    padding: var(--space-2);
  }
  .collection-actions .btn {
    min-width: 0;
  }
  .sidebar {
    width: var(--sidebar-width);
    min-width: var(--sidebar-width);
    flex-shrink: 0;
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
      padding-bottom: var(--safe-area-bottom);
    }

    .detail-shown {
      display: none;
    }
  }
</style>
