<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    bulkOperateCollectionsMutation,
    bulkOperateItemsMutation,
    getLibrariesOptions,
    getPublicDatasetStatusOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { defaultFilters, uiState, type FilterState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { filterAvailableValues, toggleSelectedValue } from "../utils/popupSelection";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import BulkOperationsCard from "../components/BulkOperationsCard.svelte";
  import CardColumn from "../components/CardColumn.svelte";
  import CheckboxList from "../components/CheckboxList.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import RangeFields from "../components/RangeFields.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";

  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());
  let datasetEnabled = $derived(datasetQuery.data?.enabled ?? false);

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

  const librariesQuery = createQuery(() => ({
    ...getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarSource === "library",
  }));
  let libraries = $derived(librariesQuery.data ?? []);
  let metadataIssueOptions = $derived(
    sidebarDomain.metadataIssuesFor(uiState.sidebarTab, datasetEnabled),
  );

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

  const bulkSetCollectionMonitoredRequest = createMutation(() => bulkOperateCollectionsMutation());
  const bulkItemsRequest = createMutation(() => bulkOperateItemsMutation());

  let bulkActionBusy = $derived(
    bulkItemsRequest.isPending || bulkSetCollectionMonitoredRequest.isPending,
  );

  let catalogDraft = $state($state.snapshot(uiState.catalogFilters));

  function apply() {
    if (uiState.sidebarSource === "overturedb") {
      uiState.catalogFilters = $state.snapshot(catalogDraft);
      uiState.closePopup();
      return;
    }
    uiState.setFilters({
      ...$state.snapshot(filters),
      overtureDb: datasetEnabled ? filters.overtureDb : "all",
      themerrDb: datasetEnabled ? filters.themerrDb : "all",
    });
    uiState.closePopup();
  }

  function clear() {
    draft = defaultFilters();
    catalogDraft = sidebarDomain.defaultCatalogFilters();
  }
</script>

<PopupShell title="Filters & operations" onclose={() => uiState.closePopup()}>
  <CardColumn>
    {#if uiState.sidebarSource === "overturedb"}
      <div class="option-card filter-grid">
        {#each sidebarDomain.CATALOG_FILTER_KEYS as key (key)}
          {#if key !== "seasonPosters" || uiState.sidebarTab === "show"}
            <span class="form-label">{sidebarDomain.CATALOG_FILTER_LABELS[key]}</span>
            <SegmentedControl
              label={sidebarDomain.CATALOG_FILTER_LABELS[key]}
              options={MEDIA_SERVER_OPTIONS}
              bind:value={catalogDraft[key]}
            />
          {/if}
        {/each}
      </div>
    {:else}
      {#if librariesQuery.isError}
        <div class="option-card">
          <span class="form-label">Libraries</span>
          <p class="hint">
            {errorMessage(librariesQuery.error, "Failed to load libraries")}
          </p>
        </div>
      {:else if libraries.length > 1}
        <div class="option-card">
          <div class="heading-row">
            <span class="form-label">Libraries</span>
            <p class="hint">
              {filters.libraryIds.length === 0
                ? "Showing all libraries"
                : `${filters.libraryIds.length} of ${libraries.length} selected`}
            </p>
          </div>
          <CheckboxList
            options={libraries.map((library) => ({
              value: library.id,
              label: library.title,
              count: library.count,
            }))}
            selected={filters.libraryIds}
            ontoggle={(id) => (draft.libraryIds = toggleSelectedValue(filters.libraryIds, id))}
          />
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

          {#if uiState.sidebarMode === "collections"}
            <label class="form-label"
              >Collection size
              <select bind:value={draft.collectionSize}>
                <option value="all">All collections</option>
                <option value="empty">Empty collections</option>
                <option value="below_minimum">Below minimum</option>
              </select>
            </label>
          {/if}
          {#if uiState.sidebarMode === "items"}
            <span class="form-label">Media server</span>
            <SegmentedControl
              label="Media Server"
              options={MEDIA_SERVER_OPTIONS}
              bind:value={draft.mediaServer}
            />

            <span class="form-label">Art</span>
            <SegmentedControl
              label="Art Status"
              options={COMPLETE_OPTIONS}
              bind:value={draft.art}
            />

            <span class="form-label">Aspect ratio</span>
            <SegmentedControl
              label="Aspect Ratio"
              options={ASPECT_RATIO_OPTIONS}
              bind:value={draft.aspectRatio}
            />
          {/if}

          <span class="form-label">Theme music</span>
          <SegmentedControl
            label="Theme Music Status"
            options={COMPLETE_OPTIONS}
            bind:value={draft.theme}
          />

          {#if uiState.sidebarMode === "items" && datasetEnabled}
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
        </div>
      </div>

      {#if uiState.sidebarMode === "items"}
        <section class="option-card filter-section art" aria-label="Art">
          <span class="form-label">Art</span>
          <div class="filter-part">
            <div class="heading-row">
              <span class="part-label">Resolution</span>
              <SegmentedControl
                --segmented-width="auto"
                --segmented-margin="0"
                label="Resolution Art Type"
                options={RESOLUTION_ART_OPTIONS}
                bind:value={draft.resolution.artType}
              />
            </div>
            <RangeFields
              minLabel="Min width (px)"
              maxLabel="Max width (px)"
              bind:min={draft.resolution.min}
              bind:max={draft.resolution.max}
            />
            <p class="hint">Artwork without a known width is hidden while a limit is set.</p>
          </div>

          <div class="filter-part">
            <div class="heading-row">
              <span class="part-label">Source</span>
              <SegmentedControl
                --segmented-width="auto"
                --segmented-margin="0"
                label="Art Source Art Type"
                options={ART_SOURCE_ART_OPTIONS}
                bind:value={draft.artSource.artType}
              />
            </div>
            <CheckboxList
              options={sidebarDomain.ART_SOURCES.map((source) => ({
                value: source,
                label: sidebarDomain.ART_SOURCE_LABELS[source],
              }))}
              selected={draft.artSource.sources}
              ontoggle={(source) =>
                (draft.artSource.sources = toggleSelectedValue(draft.artSource.sources, source))}
            />
            <p class="hint">
              Artwork the OvertureDB entry lists counts as OvertureDB, whichever site hosts it.
            </p>
          </div>
        </section>
      {/if}

      <section class="option-card filter-section theme" aria-label="Themes">
        <span class="form-label">Themes</span>
        <div class="filter-part">
          <span class="part-label">Length</span>
          <RangeFields
            minLabel="Min length (s)"
            maxLabel="Max length (s)"
            bind:min={draft.themeLength.min}
            bind:max={draft.themeLength.max}
          />
          <p class="hint">Themes without a known length are hidden while a limit is set.</p>
        </div>

        {#if uiState.sidebarMode === "items"}
          <div class="filter-part">
            <span class="part-label">Source</span>
            <CheckboxList
              options={sidebarDomain.THEME_SOURCES.map((source) => ({
                value: source,
                label: sidebarDomain.THEME_SOURCE_LABELS[source],
              }))}
              selected={draft.themeSources}
              ontoggle={(source) =>
                (draft.themeSources = toggleSelectedValue(draft.themeSources, source))}
            />
          </div>
        {/if}
      </section>

      {#if uiState.sidebarMode === "items"}
        <section class="option-card" aria-label="Metadata issues">
          <div class="heading-row">
            <span class="form-label">Metadata issues</span>
            <SegmentedControl
              --segmented-width="auto"
              --segmented-margin="0"
              label="Metadata Issues Match Mode"
              options={MATCH_MODE_OPTIONS}
              bind:value={draft.metadataIssues.mode}
            />
          </div>
          <CheckboxList
            options={metadataIssueOptions.map((flag) => ({
              value: flag,
              label: sidebarDomain.METADATA_ISSUE_CHECKS[flag].label,
            }))}
            selected={draft.metadataIssues.flags}
            ontoggle={(flag) =>
              (draft.metadataIssues.flags = toggleSelectedValue(draft.metadataIssues.flags, flag))}
          />
        </section>
      {/if}

      <BulkOperationsCard
        {filters}
        publicDatasetEnabled={datasetEnabled}
        itemsRequest={bulkItemsRequest}
        collectionsRequest={bulkSetCollectionMonitoredRequest}
      />
    {/if}
  </CardColumn>

  {#snippet footer()}
    <button class="btn btn-ghost" onclick={clear} disabled={bulkActionBusy}>Reset filters</button>
    <button class="btn btn-ghost" onclick={() => uiState.closePopup()}>Cancel</button>
    <button class="btn btn-primary" onclick={apply} disabled={bulkActionBusy}>Apply filters</button>
  {/snippet}
</PopupShell>

<style>
  .filter-section,
  .filter-part {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .filter-section {
    gap: var(--space-4);
  }

  .art {
    --section-accent: var(--asset-art);
  }

  .theme {
    --section-accent: var(--asset-theme);
  }

  .filter-section > .form-label {
    color: var(--section-accent);
  }

  .part-label {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-secondary);
  }

  /* Label column + control column; collapses to stacked rows on phones. */
  .filter-grid {
    --segmented-margin: 0;
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    align-items: center;
    gap: var(--space-2) var(--space-4);
  }

  @media (max-width: 480px) {
    .filter-grid {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-1);
    }

    .filter-grid > .form-label:not(:first-child) {
      margin-top: var(--space-2);
    }
  }
</style>
