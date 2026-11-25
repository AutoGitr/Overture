<script lang="ts">
  import LayersPlus from "@lucide/svelte/icons/layers-plus";
  import type {
    CatalogEntryRow,
    CollectionRead,
    MediaItemRead,
  } from "../../generated/rest/types.gen";
  import {
    goToCatalogEntry,
    routedCatalogEntry,
    goToCollection,
    goToCollectionView,
    goToNewCollection,
    sidebarGroup,
    openSidebarGroup,
    goToCollectionsList,
    goToGroup,
    routedGroup,
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
  import { collectionArtDisplayUrl, itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import {
    activeFilterCount,
    catalogFilterCount,
    defaultCatalogFilters,
    defaultTmdbFilters,
  } from "../utils/sidebarFilters";
  import { SidebarListing } from "../utils/sidebarListing.svelte";
  import { searchFieldGroups, searchPlaceholder } from "../utils/sidebarSearches";
  import { sidebarGroupNames, statusTone, type CollectionGroupRow } from "../utils/sidebarShared";
  import { UNMANAGED_GROUP } from "../../generated/settings";
  import { readJson, writeJson } from "../utils/storage";
  import DataStatus from "./DataStatus.svelte";
  import SidebarControls from "./SidebarControls.svelte";
  import SidebarGroupBrowser from "./SidebarGroupBrowser.svelte";
  import SidebarGroupRow from "./SidebarGroupRow.svelte";
  import SidebarList from "./SidebarList.svelte";
  import SidebarRow from "./SidebarRow.svelte";
  import SidebarTabs from "./SidebarTabs.svelte";
  import TmdbSearchResults from "./TmdbSearchResults.svelte";
  import { filterState, defaultFilters } from "../stores/filterState.svelte";

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

  const listing = new SidebarListing(() => ({ movies, shows, loading, error }));
  $effect(() => sidebarState.show(listing));
  let {
    catalog,
    collectionsQuery,
    groupsQuery,
    catalogMovies,
    catalogShows,
    catalogCollections,
    collections,
    catalogQuery,
    catalogEntries,
    groupView,
    currentGroup,
    sortFields,
    sort,
    tmdbFilterKeys,
    catalogRows,
    libraryItems,
    filteredItems,
    filteredCollections,
    collectionGroups,
    visibleCollections,
  } = $derived(listing);

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

  let searchingTmdb = $derived(uiState.searchingTmdb);

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
    artStatus={statusTone(
      item.art_status,
      downloadState.isDownloadingType(item.id, "art"),
    )}
    themeStatus={statusTone(
      item.assets.theme.status,
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
    artStatus={statusTone(collection.art_status, false)}
    themeStatus={statusTone(
      collection.assets.theme.status,
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

{#snippet collectionGroupRow(group: CollectionGroupRow, _index: number, style: string)}
  <SidebarGroupRow
    title={group.title}
    count={group.collections}
    {style}
    locked={group.title === UNMANAGED_GROUP}
    onselect={() =>
      // Unmanaged gathers what Overture does not manage, so it has no page.
      // On a phone the sidebar stays in front, listing the group's collections.
      group.title === UNMANAGED_GROUP ? openSidebarGroup(group.title) : goToGroup(group.title)}
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
        ? sidebarGroupNames(groupsQuery.data ?? [], collections).length
        : collections.length}
  />

  <SidebarControls
    {section}
    searchGroups={searchFieldGroups(
      uiState.sidebarSource,
      uiState.sidebarMode,
      uiState.sidebarTab,
      settingsState.current.tmdb_configured,
    )}
    placeholder={searchPlaceholder(
      uiState.sidebarMode,
      uiState.sidebarTab,
      uiState.searchField,
      uiState.sidebarSource === "overturedb"
        ? catalogRows.length
        : uiState.sidebarMode === "collections"
          ? filteredCollections.length
          : filteredItems.length,
    )}
    {sortFields}
    filtersOpen={uiState.openPopup === "filters"}
    activeFilters={searchingTmdb
      ? tmdbFilterKeys.filter((key) => filterState.tmdb[key] !== "all").length
      : uiState.sidebarSource === "overturedb"
      ? catalogFilterCount(filterState.catalog, uiState.sidebarTab)
      : activeFilterCount(
          filterState.current,
          catalog.enabled,
          uiState.sidebarMode,
        )}
    onResetFilters={() => {
      if (searchingTmdb) filterState.tmdb = defaultTmdbFilters();
      else if (uiState.sidebarSource === "overturedb")
        filterState.catalog = defaultCatalogFilters();
      else filterState.set(defaultFilters());
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
    onSetSort={listing.setSort}
  />

  {#if uiState.sidebarSource === "library" && uiState.sidebarMode === "collections" && settingsState.current.collections_supported}
    <div class="collection-actions">
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        aria-label="Create collection"
        title="Create collection"
        onclick={() => openDetail(() => goToNewCollection())}
        ><LayersPlus size={14} />Create</button
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
            filters={filterState.tmdb}
            filterKeys={tmdbFilterKeys}
            by={uiState.tmdbSearchBy ?? "title"}
            sortField={sort.field}
            sortDir={sort.dir}
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
          filters={filterState.tmdb}
          filterKeys={tmdbFilterKeys}
          by={uiState.tmdbSearchBy ?? "title"}
          sortField={sort.field}
          sortDir={sort.dir}
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
          onback={() => (routedGroup() === null ? openSidebarGroup(null) : goToCollectionsList())}
          onopen={currentGroup === UNMANAGED_GROUP
            ? null
            : (group) => openDetail(() => goToGroup(group.title))}
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
    grid-template-columns: minmax(0, 1fr);
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
