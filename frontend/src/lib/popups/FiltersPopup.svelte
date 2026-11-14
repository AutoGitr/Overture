<script lang="ts">
  import { CatalogBrowsing } from "../utils/catalogBrowsing.svelte";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    bulkOperateCollectionsMutation,
    bulkOperateItemsMutation,
    getCollectionCapabilitiesOptions,
    getLibrariesOptions,
    listCatalogEntriesOptions,
    listCollectionsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { defaultFilters, uiState, type FilterState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { filterAvailableValues, toggleSelectedValue } from "../utils/popupSelection";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import BulkOperationsCard from "../components/BulkOperationsCard.svelte";
  import CardColumn from "../components/CardColumn.svelte";
  import CatalogDraftsCard from "../components/CatalogDraftsCard.svelte";
  import CheckboxList from "../components/CheckboxList.svelte";
  import FieldRow from "../components/FieldRow.svelte";
  import PopupSection from "../components/PopupSection.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import RangeFields from "../components/RangeFields.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import { setSectionView } from "../stores/sectionState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { alphabetical } from "../utils/alphabetical";

  setSectionView("filters");
  const id = $props.id();
  const catalogBrowsing = new CatalogBrowsing();
  let catalogEnabled = $derived(catalogBrowsing.enabled);

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
  const MEMBERS_OPTIONS = [
    ["all", "All"],
    ["managed", "Overture"],
    ["unmanaged", "Unmanaged"],
  ] as const;
  const KIND_OPTIONS = [
    ["all", "All"],
    ["regular", "Regular"],
    ["smart", "Smart"],
  ] as const;
  const HOLDS_OPTIONS = [
    ["all", "All"],
    ["movie", "Movies"],
    ["show", "Shows"],
    ["both", "Both"],
  ] as const;
  const ORIGIN_OPTIONS = [
    ["all", "All"],
    ["single", "One collection"],
    ["set", "One per value"],
  ] as const;
  const SYNC_OPTIONS = [
    ["all", "All"],
    ["synced", "Synced"],
    ["failed", "Failed"],
  ] as const;
  const SIZE_OPTIONS = [
    ["all", "All"],
    ["empty", "Empty"],
    ["below_minimum", "Below minimum"],
  ] as const;
  const MATCH_MODE_OPTIONS = [
    ["any", "Any selected"],
    ["all", "All selected"],
  ] as const;

  /** The choices of each section that picks one value. */
  const CHOICES = {
    monitored: { options: MONITOR_OPTIONS },
    art: { options: COMPLETE_OPTIONS },
    aspectRatio: { options: ASPECT_RATIO_OPTIONS },
    theme: { options: COMPLETE_OPTIONS },
    overtureDb: { options: COMPLETE_OPTIONS },
    themerrDb: { options: COMPLETE_OPTIONS },
    collectionMembers: { options: MEMBERS_OPTIONS },
    collectionHolds: { options: HOLDS_OPTIONS },
    collectionKind: { options: KIND_OPTIONS },
    collectionOrigin: { options: ORIGIN_OPTIONS },
    collectionSync: { options: SYNC_OPTIONS },
    collectionSize: { options: SIZE_OPTIONS },
    mediaServer: { options: MEDIA_SERVER_OPTIONS },
  } as const;

  const capabilities = createQuery(() => ({
    ...getCollectionCapabilitiesOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "collections",
  }));

  const librariesQuery = createQuery(() => ({
    ...getLibrariesOptions(
      uiState.sidebarMode === "collections" ? {} : { query: { media_type: uiState.sidebarTab } },
    ),
    enabled: uiState.sidebarSource === "library",
  }));
  let libraries = $derived(librariesQuery.data ?? []);
  const collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions(),
    enabled:
      uiState.sidebarSource === "library" &&
      uiState.sidebarMode === "items" &&
      settingsState.current.collections_supported,
  }));
  let collections = $derived(
    alphabetical(
      (collectionsQuery.data ?? []).filter((row) => row.media_types.includes(uiState.sidebarTab)),
      (row) => row.title,
    ),
  );
  let metadataIssueOptions = $derived(
    sidebarDomain.metadataIssuesFor(uiState.sidebarTab, catalogEnabled, uiState.sidebarMode),
  );
  let groupedSections = $derived.by(() => {
    const shown = sidebarDomain.filterSections(uiState.sidebarMode, {
      tab: uiState.sidebarTab,
      catalogEnabled,
      smart: !!capabilities.data?.smart,
      collections: settingsState.current.collections_supported,
    });
    return (Object.keys(sidebarDomain.FILTER_GROUPS) as sidebarDomain.FilterGroup[])
      .map((group) => [group, shown.filter((key) => sidebarDomain.FILTERS[key].group === group)] as const)
      .filter(([, keys]) => keys.length > 0);
  });

  /** Splits *keys* into runs of neighbours offering the same choices. */
  function choiceRuns(keys: readonly sidebarDomain.FilterKey[]): sidebarDomain.FilterKey[][] {
    const runs: sidebarDomain.FilterKey[][] = [];
    for (const key of keys) {
      const run = runs.at(-1);
      const previous = run?.at(-1);
      if (run && previous && choicesOf(previous) === choicesOf(key)) run.push(key);
      else runs.push([key]);
    }
    return runs;
  }

  function choicesOf(key: sidebarDomain.FilterKey) {
    return key in CHOICES ? CHOICES[key as keyof typeof CHOICES].options : key;
  }

  let filters = $derived<FilterState>({
    ...draft,
    libraryIds: librariesQuery.isSuccess
      ? filterAvailableValues(
          draft.libraryIds,
          libraries.map((library) => library.id),
        )
      : draft.libraryIds,
    collectionId:
      collectionsQuery.isSuccess && !collections.some((row) => row.id === draft.collectionId)
        ? null
        : draft.collectionId,
  });

  const bulkSetCollectionMonitoredRequest = createMutation(() => bulkOperateCollectionsMutation());
  const bulkItemsRequest = createMutation(() => bulkOperateItemsMutation());

  let bulkActionBusy = $derived(
    bulkItemsRequest.isPending || bulkSetCollectionMonitoredRequest.isPending,
  );

  let catalogDraft = $state($state.snapshot(uiState.catalogFilters));
  const catalogQuery = createQuery(() => ({
    ...listCatalogEntriesOptions({
      query: {
        media_type: uiState.sidebarMode === "collections" ? "collection" : uiState.sidebarTab,
      },
    }),
    enabled: uiState.sidebarSource === "overturedb",
  }));
  /** The entries the draft filters and the search match, as the sidebar would list them. */
  let catalogEntries = $derived(
    sidebarDomain.filterCatalogEntries({
      entries: catalogQuery.data ?? [],
      filters: catalogDraft,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
    }),
  );

  /** Nothing differs from the filters in use, so Apply would change nothing. */
  let unchanged = $derived(
    uiState.sidebarSource === "overturedb"
      ? JSON.stringify(catalogDraft) === JSON.stringify(uiState.catalogFilters)
      : JSON.stringify(filters) === JSON.stringify(uiState.currentFilters),
  );

  function apply() {
    if (uiState.sidebarSource === "overturedb") {
      uiState.catalogFilters = $state.snapshot(catalogDraft);
      uiState.closePopup();
      return;
    }
    uiState.setFilters({
      ...$state.snapshot(filters),
      overtureDb: catalogEnabled ? filters.overtureDb : "all",
      themerrDb: catalogEnabled ? filters.themerrDb : "all",
    });
    uiState.closePopup();
  }

  function clear() {
    draft = defaultFilters();
    catalogDraft = sidebarDomain.defaultCatalogFilters();
  }
</script>

{#snippet filter(key: sidebarDomain.FilterKey)}
  {@const label = sidebarDomain.FILTERS[key].label}
  {#if key === "resolution"}
    <FieldRow {label}>
      <SegmentedControl
        label="Resolution art type"
        options={RESOLUTION_ART_OPTIONS}
        bind:value={draft.resolution.artType}
      />
    </FieldRow>
    <RangeFields
      minLabel="Min width (px)"
      maxLabel="Max width (px)"
      bind:min={draft.resolution.min}
      bind:max={draft.resolution.max}
    />
    <p class="hint">Artwork without a known width is hidden while a limit is set.</p>
  {:else if key === "artSource"}
    <FieldRow {label}>
      <SegmentedControl
        label="Art source art type"
        options={ART_SOURCE_ART_OPTIONS}
        bind:value={draft.artSource.artType}
      />
    </FieldRow>
    <CheckboxList
      options={sidebarDomain.ART_SOURCES.map((source) => ({
        value: source,
        label: sidebarDomain.ART_SOURCE_LABELS[source],
      }))}
      selected={draft.artSource.sources}
      ontoggle={(source) =>
        (draft.artSource.sources = toggleSelectedValue(draft.artSource.sources, source))}
    />
  {:else if key === "collection"}
    <FieldRow {label} for={`${id}-collection`}>
      <select
        id={`${id}-collection`}
        value={filters.collectionId === null ? "" : String(filters.collectionId)}
        onchange={(event) =>
          (draft.collectionId = event.currentTarget.value
            ? Number(event.currentTarget.value)
            : null)}
      >
        <option value="">Any collection</option>
        {#each collections as row (row.id)}
          <option value={String(row.id)}>{row.title}</option>
        {/each}
      </select>
    </FieldRow>
    {#if collectionsQuery.isError}
      <p class="hint">{errorMessage(collectionsQuery.error, "Failed to load collections")}</p>
    {/if}
  {:else if key === "themeLength"}
    <FieldRow {label} />
    <RangeFields
      minLabel="Min length (s)"
      maxLabel="Max length (s)"
      bind:min={draft.themeLength.min}
      bind:max={draft.themeLength.max}
    />
    <p class="hint">Themes without a known length are hidden while a limit is set.</p>
  {:else if key === "themeSources"}
    <FieldRow {label} />
    <CheckboxList
      options={sidebarDomain.THEME_SOURCES.map((source) => ({
        value: source,
        label: sidebarDomain.THEME_SOURCE_LABELS[source],
      }))}
      selected={draft.themeSources}
      ontoggle={(source) => (draft.themeSources = toggleSelectedValue(draft.themeSources, source))}
    />
  {:else if key === "metadataIssues"}
    <FieldRow label="Match">
      <SegmentedControl
        label="Metadata issues match mode"
        options={MATCH_MODE_OPTIONS}
        bind:value={draft.metadataIssues.mode}
      />
    </FieldRow>
    <CheckboxList
      options={metadataIssueOptions.map((flag) => ({
        value: flag,
        label: sidebarDomain.METADATA_ISSUE_CHECKS[flag].label,
      }))}
      selected={draft.metadataIssues.flags}
      ontoggle={(flag) =>
        (draft.metadataIssues.flags = toggleSelectedValue(draft.metadataIssues.flags, flag))}
    />
  {:else if key !== "libraries"}
    <FieldRow {label}>
      <SegmentedControl
        {label}
        options={CHOICES[key].options}
        bind:value={() => draft[key], (value) => Object.assign(draft, { [key]: value })}
      />
    </FieldRow>
  {/if}
{/snippet}

<PopupShell title="Filters & operations" onclose={() => uiState.closePopup()}>
  <!-- Names share one column and every control fills the rest of the row,
       with its options at equal widths; where that leaves a control too
       narrow for its options, it moves under its name. -->
  <CardColumn
    --field-label-flex="0 0 clamp(7rem, 30%, 11rem)"
    --field-control-flex="1 1 0"
    --field-control-min="min(100%, 17rem)"
    --field-segmented-width="100%"
    --field-input-flex="1 1 auto"
    --segment-flex="1 1 0"
    --segmented-wrap="nowrap"
  >
    {#if uiState.sidebarSource === "overturedb"}
      <PopupSection label={sidebarDomain.FILTER_GROUPS.status}>
        {#each sidebarDomain.CATALOG_FILTER_KEYS as key (key)}
          {#if key !== "seasonPosters" || uiState.sidebarTab === "show"}
            <FieldRow label={sidebarDomain.CATALOG_FILTER_LABELS[key]}>
              <SegmentedControl
                label={sidebarDomain.CATALOG_FILTER_LABELS[key]}
                options={MEDIA_SERVER_OPTIONS}
                bind:value={catalogDraft[key]}
              />
            </FieldRow>
          {/if}
        {/each}
      </PopupSection>
      <CatalogDraftsCard entries={catalogEntries} />
    {:else}
      {#each groupedSections as [group, keys] (group)}
        {@const title = sidebarDomain.FILTER_GROUPS[group]}
        {#if title}
          <PopupSection label={title}>
            <!-- Status holds one-line choices only, evenly spaced as one run;
                 art and theme filters span rows, so a rule ends each run. -->
            {#each group === "status" ? [keys] : choiceRuns(keys) as run (run[0])}
              <div class="choice-run" class:ruled={group !== "status"}>
                {#each run as key (key)}
                  {@render filter(key)}
                {/each}
              </div>
            {/each}
          </PopupSection>
        {:else}
          {#each keys as key (key)}
            {#if key !== "libraries"}
              <PopupSection label={sidebarDomain.FILTERS[key].label}>
                {@render filter(key)}
              </PopupSection>
            {:else if librariesQuery.isError}
              <PopupSection label={sidebarDomain.FILTERS.libraries.label}>
                <p class="hint">{errorMessage(librariesQuery.error, "Failed to load libraries")}</p>
              </PopupSection>
            {:else if libraries.length > 1}
              <PopupSection
                label={sidebarDomain.FILTERS.libraries.label}
                description={filters.libraryIds.length === 0
                  ? "All libraries"
                  : `${filters.libraryIds.length} of ${libraries.length} selected`}
              >
                <CheckboxList
                  options={libraries.map((library) => ({
                    value: library.id,
                    label: library.title,
                    count: library.count,
                  }))}
                  selected={filters.libraryIds}
                  ontoggle={(id) =>
                    (draft.libraryIds = toggleSelectedValue(filters.libraryIds, id))}
                />
              </PopupSection>
            {/if}
          {/each}
        {/if}
      {/each}

      <BulkOperationsCard
        {filters}
        catalogEnabled={catalogEnabled}
        itemsRequest={bulkItemsRequest}
        collectionsRequest={bulkSetCollectionMonitoredRequest}
      />
    {/if}
  </CardColumn>

  {#snippet footer()}
    <button class="btn btn-secondary actions-start" onclick={clear} disabled={bulkActionBusy}
      >Reset filters</button
    >
    <button class="btn btn-secondary" onclick={() => uiState.closePopup()}>Cancel</button>
    <button
      class="btn btn-primary"
      onclick={apply}
      disabled={bulkActionBusy || unchanged}
      title={unchanged ? "These are the filters in use" : undefined}>Apply filters</button
    >
  {/snippet}
</PopupShell>

<style>
  .choice-run {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  /* Filters offering the same choices read as one block. */
  .choice-run + .choice-run.ruled {
    padding-top: var(--space-2);
    border-top: var(--border-subtle);
  }
</style>
