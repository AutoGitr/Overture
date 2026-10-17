<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import {
    bulkSetCollectionMonitoredMutation,
    bulkOperateItemsMutation,
    getLibrariesOptions,
    listCollectionsOptions,
    listItemsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { publicDatasetState } from "../stores/publicDatasetState.svelte";
  import { defaultFilters, uiState, type FilterState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { filterAvailableValues, toggleSelectedValue } from "../utils/popupSelection";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import BulkOperationsCard from "../components/BulkOperationsCard.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";

  let draft = $state<FilterState>($state.snapshot(uiState.currentFilters));

  const MONITOR_OPTIONS = [
    ["all", "All"],
    ["monitored", "Monitored"],
    ["unmonitored", "Unmonitored"],
  ] as const;
  const COMPLETE_OPTIONS = [
    ["all", "All"],
    ["complete", "Complete"],
    ["incomplete", "Incomplete"],
  ] as const;
  const ASPECT_RATIO_OPTIONS = [
    ["all", "All"],
    ["correct", "Correct"],
    ["incorrect", "Incorrect"],
  ] as const;
  const MEDIA_SERVER_OPTIONS = [
    ["all", "All"],
    ["present", "Present"],
    ["missing", "Missing"],
  ] as const;
  const RESOLUTION_ART_OPTIONS = [
    ["poster", "Poster"],
    ["background", "Background"],
  ] as const;
  const ART_SOURCE_ART_OPTIONS = [
    ["any", "Any art"],
    ["poster", "Poster"],
    ["background", "Background"],
  ] as const;
  const MATCH_MODE_OPTIONS = [
    ["any", "Any selected"],
    ["all", "All selected"],
  ] as const;

  onMount(() => {
    if (!publicDatasetState.loaded) {
      void publicDatasetState.refresh();
    }
  });

  const librariesQuery = createQuery(() =>
    getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  let libraries = $derived(librariesQuery.data ?? []);
  let missingMetadataFlags = $derived(sidebarDomain.missingMetadataFlagsFor(uiState.sidebarTab));

  const itemsQuery = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "items",
  }));
  const collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "collections",
  }));

  /** The draft without selections for libraries that no longer exist. */
  let filters = $derived<FilterState>({
    ...draft,
    libraryIds: librariesQuery.isSuccess
      ? filterAvailableValues(
          draft.libraryIds,
          libraries.map((library) => library.id),
        )
      : draft.libraryIds,
  });

  const bulkSetCollectionMonitoredRequest = createMutation(() =>
    bulkSetCollectionMonitoredMutation(),
  );
  const bulkItemsRequest = createMutation(() => bulkOperateItemsMutation());

  let bulkActionBusy = $derived(
    bulkItemsRequest.isPending || bulkSetCollectionMonitoredRequest.isPending,
  );

  let filteredItems = $derived(
    uiState.sidebarMode === "items"
      ? sidebarDomain.filterSidebarItems({
          items: itemsQuery.data?.items ?? [],
          filters,
          publicDatasetEnabled: publicDatasetState.enabled,
          searchQuery: uiState.searchQuery,
          searchField: uiState.searchField,
          sortField: "title",
          sortDir: "asc",
        })
      : [],
  );

  let filteredCollections = $derived(
    uiState.sidebarMode === "collections"
      ? sidebarDomain.filterSidebarCollections({
          collections: collectionsQuery.data ?? [],
          filters,
          searchQuery: uiState.searchQuery,
        })
      : [],
  );

  let noun = $derived(
    uiState.sidebarMode === "items"
      ? uiState.sidebarTab === "movie"
        ? "movies"
        : "shows"
      : "collections",
  );
  let resultsReady = $derived(
    uiState.sidebarMode === "collections" ? collectionsQuery.isSuccess : itemsQuery.isSuccess,
  );

  function apply() {
    uiState.setFilters({
      ...$state.snapshot(filters),
      overtureDb: publicDatasetState.enabled ? filters.overtureDb : "all",
      themerrDb: publicDatasetState.enabled ? filters.themerrDb : "all",
    });
    uiState.closePopup();
  }

  function clear() {
    draft = defaultFilters();
  }
</script>

<PopupShell
  title="Filters & operations"
  width="min(720px, 100%)"
  onclose={() => uiState.closePopup()}
>
  {#if librariesQuery.isError}
    <div class="option-card">
      <span class="form-label">Libraries</span>
      <p class="filter-hint">{errorMessage(librariesQuery.error, "Failed to load libraries")}</p>
    </div>
  {:else if libraries.length > 1}
    <div class="option-card">
      <div class="option-header">
        <span class="form-label">Libraries</span>
        <p class="filter-hint">
          {filters.libraryIds.length === 0
            ? "Showing all libraries"
            : `${filters.libraryIds.length} of ${libraries.length} selected`}
        </p>
      </div>
      <div class="check-list">
        {#each libraries as lib (lib.id)}
          <label class="checkbox-group">
            <input
              type="checkbox"
              checked={filters.libraryIds.includes(lib.id)}
              onchange={() => (draft.libraryIds = toggleSelectedValue(filters.libraryIds, lib.id))}
            />
            <span class="check-label">
              {lib.title}
              <span class="check-count">{lib.count}</span>
            </span>
          </label>
        {/each}
      </div>
    </div>
  {/if}

  <div class="option-card">
    <div class="filter-grid">
      <span class="form-label">Monitor status</span>
      <SegmentedControl
        label="Monitor Status"
        options={MONITOR_OPTIONS}
        bind:value={draft.monitored}
      />

      {#if uiState.sidebarMode === "items"}
        <span class="form-label">Art</span>
        <SegmentedControl label="Art Status" options={COMPLETE_OPTIONS} bind:value={draft.art} />
      {/if}

      <span class="form-label">Theme music</span>
      <SegmentedControl
        label="Theme Music Status"
        options={COMPLETE_OPTIONS}
        bind:value={draft.theme}
      />

      {#if uiState.sidebarMode === "items"}
        {#if publicDatasetState.enabled}
          <span class="form-label">OvertureDB</span>
          <SegmentedControl
            label="OvertureDB Status"
            options={COMPLETE_OPTIONS}
            bind:value={draft.overtureDb}
          />

          <span class="form-label">ThemerrDB</span>
          <SegmentedControl
            label="ThemerrDB Status"
            options={COMPLETE_OPTIONS}
            bind:value={draft.themerrDb}
          />
        {/if}

        <span class="form-label">Aspect ratio</span>
        <SegmentedControl
          label="Aspect Ratio"
          options={ASPECT_RATIO_OPTIONS}
          bind:value={draft.aspectRatio}
        />

        <span class="form-label">Media server</span>
        <SegmentedControl
          label="Media Server"
          options={MEDIA_SERVER_OPTIONS}
          bind:value={draft.mediaServer}
        />
      {/if}
    </div>
  </div>

  {#if uiState.sidebarMode === "items"}
    <div class="option-card">
      <span class="form-label">Resolution</span>
      <div class="filter-grid">
        <span class="form-label">Art type</span>
        <SegmentedControl
          label="Resolution Art Type"
          options={RESOLUTION_ART_OPTIONS}
          bind:value={draft.resolution.artType}
        />
      </div>
      <div class="range-grid">
        <div class="range-field">
          <label class="form-label" for="res-min">Min width (px)</label>
          <input
            id="res-min"
            type="number"
            class="number-input"
            min="1"
            bind:value={draft.resolution.min}
          />
        </div>
        <div class="range-field">
          <label class="form-label" for="res-max">Max width (px)</label>
          <input
            id="res-max"
            type="number"
            class="number-input"
            min="1"
            bind:value={draft.resolution.max}
          />
        </div>
      </div>
      <p class="filter-hint">
        Leave a limit empty for no limit. Artwork without a known width is hidden while either limit
        is set.
      </p>
    </div>
  {/if}

  <div class="option-card">
    <span class="form-label">Theme length</span>
    <div class="range-grid">
      <div class="range-field">
        <label class="form-label" for="theme-min">Min length (s)</label>
        <input
          id="theme-min"
          type="number"
          class="number-input"
          min="1"
          bind:value={draft.themeLength.min}
        />
      </div>
      <div class="range-field">
        <label class="form-label" for="theme-max">Max length (s)</label>
        <input
          id="theme-max"
          type="number"
          class="number-input"
          min="1"
          bind:value={draft.themeLength.max}
        />
      </div>
    </div>
    <p class="filter-hint">
      Leave a limit empty for no limit. Themes without a known length are hidden while either limit
      is set.
    </p>
  </div>

  {#if uiState.sidebarMode === "items"}
    <div class="option-card">
      <div class="option-header">
        <span class="form-label">Art source</span>
        <SegmentedControl
          label="Art Source Art Type"
          options={ART_SOURCE_ART_OPTIONS}
          bind:value={draft.artSource.artType}
        />
      </div>
      <p class="filter-hint">
        {draft.artSource.sources.length === 0
          ? "Showing all sources"
          : `Showing items whose ${draft.artSource.artType === "any" ? "poster or background" : draft.artSource.artType} came from any selected source`}
      </p>
      <div class="check-list">
        {#each sidebarDomain.ART_SOURCES as source (source)}
          <label class="checkbox-group">
            <input
              type="checkbox"
              checked={draft.artSource.sources.includes(source)}
              onchange={() =>
                (draft.artSource.sources = toggleSelectedValue(draft.artSource.sources, source))}
            />
            <span class="check-label">{sidebarDomain.ART_SOURCE_LABELS[source]}</span>
          </label>
        {/each}
      </div>
      <p class="filter-hint">
        Artwork the OvertureDB entry lists counts as OvertureDB, whichever site hosts it.
      </p>
    </div>

    <div class="option-card">
      <div class="option-header">
        <span class="form-label">Theme source</span>
        <p class="filter-hint">
          {draft.themeSources.length === 0
            ? "Showing all sources"
            : "Showing items whose theme came from any selected source"}
        </p>
      </div>
      <div class="check-list">
        {#each sidebarDomain.THEME_SOURCES as source (source)}
          <label class="checkbox-group">
            <input
              type="checkbox"
              checked={draft.themeSources.includes(source)}
              onchange={() =>
                (draft.themeSources = toggleSelectedValue(draft.themeSources, source))}
            />
            <span class="check-label">{sidebarDomain.THEME_SOURCE_LABELS[source]}</span>
          </label>
        {/each}
      </div>
    </div>

    <div class="option-card">
      <div class="option-header">
        <span class="form-label">Missing metadata</span>
        <SegmentedControl
          label="Missing Metadata Match Mode"
          options={MATCH_MODE_OPTIONS}
          bind:value={draft.missingMetadata.mode}
        />
      </div>
      <p class="filter-hint">
        {draft.missingMetadata.mode === "all"
          ? "Show items missing all selected fields"
          : "Show items missing any selected field"}
      </p>
      <div class="check-list">
        {#each missingMetadataFlags as flag (flag)}
          <label class="checkbox-group">
            <input
              type="checkbox"
              checked={draft.missingMetadata.flags.includes(flag)}
              onchange={() =>
                (draft.missingMetadata.flags = toggleSelectedValue(
                  draft.missingMetadata.flags,
                  flag,
                ))}
            />
            <span class="check-label">{sidebarDomain.MISSING_METADATA_CHECKS[flag].label}</span>
          </label>
        {/each}
      </div>
    </div>
  {/if}

  <BulkOperationsCard
    items={filteredItems}
    collections={filteredCollections}
    {resultsReady}
    {noun}
    itemsRequest={bulkItemsRequest}
    collectionsRequest={bulkSetCollectionMonitoredRequest}
  />

  {#snippet footer()}
    <button class="btn btn-ghost" onclick={clear} disabled={bulkActionBusy}>Reset filters</button>
    <button class="btn btn-ghost" onclick={() => uiState.closePopup()}>Cancel</button>
    <button class="btn btn-primary" onclick={apply} disabled={bulkActionBusy}>Apply filters</button>
  {/snippet}
</PopupShell>

<style>
  .option-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .option-header :global(.segmented-control) {
    width: auto;
    margin-top: 0;
  }
  .filter-hint {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    margin: 0;
  }
  /* Label column + control column; collapses to stacked rows on phones. */
  .filter-grid {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    align-items: center;
    gap: var(--space-2) var(--space-4);
  }
  .filter-grid :global(.segmented-control) {
    margin-top: 0;
  }
  .range-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .range-field {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-2);
  }
  .number-input {
    flex: 1;
    min-width: 0;
    width: 80px;
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-sm);
    font-family: var(--font-mono);
  }
  .check-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: var(--space-2) var(--space-4);
    max-height: 24vh;
    overflow-y: auto;
  }
  .check-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
  .check-count {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    font-family: var(--font-mono);
  }
  @media (max-width: 480px) {
    .range-field {
      flex-direction: column;
      align-items: stretch;
    }
    .number-input {
      width: 100%;
    }
    .filter-grid {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-1);
    }
    .filter-grid > .form-label:not(:first-child) {
      margin-top: var(--space-2);
    }
  }
</style>
