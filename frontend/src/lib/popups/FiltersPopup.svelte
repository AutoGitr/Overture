<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    bulkOperateCollectionsMutation,
    bulkOperateItemsMutation,
    getCollectionCapabilitiesOptions,
    getLibrariesOptions,
    getPublicDatasetStatusOptions,
    listCatalogEntriesOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { UNMANAGED_GROUP } from "../../generated/settings";
  import { openSidebarGroup, sidebarGroup } from "../router/routes";
  import { defaultFilters, uiState, type FilterState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { filterAvailableValues, toggleSelectedValue } from "../utils/popupSelection";
  import * as sidebarDomain from "../utils/sidebarDomain";
  import BulkOperationsCard from "../components/BulkOperationsCard.svelte";
  import CardColumn from "../components/CardColumn.svelte";
  import CatalogDraftsCard from "../components/CatalogDraftsCard.svelte";
  import CheckboxList from "../components/CheckboxList.svelte";
  import CollectionGroupActions from "../components/CollectionGroupActions.svelte";
  import FieldRow from "../components/FieldRow.svelte";
  import FilterSection from "../components/FilterSection.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import RangeFields from "../components/RangeFields.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";

  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());
  let openGroup = $derived(sidebarGroup());
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
    collectionKind: { options: KIND_OPTIONS },
    collectionSync: { options: SYNC_OPTIONS },
    collectionSize: { options: SIZE_OPTIONS },
    mediaServer: { options: MEDIA_SERVER_OPTIONS },
  } as const;

  const capabilities = createQuery(() => ({
    ...getCollectionCapabilitiesOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "collections",
  }));

  const librariesQuery = createQuery(() => ({
    ...getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarSource === "library",
  }));
  let libraries = $derived(librariesQuery.data ?? []);
  let metadataIssueOptions = $derived(
    sidebarDomain.metadataIssuesFor(uiState.sidebarTab, datasetEnabled, uiState.sidebarMode),
  );
  /** The shown filters by popup section, in order. */
  let groupedSections = $derived.by(() => {
    const shown = sidebarDomain.filterSections(uiState.sidebarMode, {
      tab: uiState.sidebarTab,
      datasetEnabled,
      smart: !!capabilities.data?.smart,
    });
    return (Object.keys(sidebarDomain.FILTER_GROUPS) as sidebarDomain.FilterGroup[])
      .map((group) => [group, shown.filter((key) => sidebarDomain.FILTERS[key].group === group)] as const)
      .filter(([, keys]) => keys.length > 0);
  });

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
  <CardColumn>
    {#if uiState.sidebarSource === "overturedb"}
      <FilterSection label={sidebarDomain.FILTER_GROUPS.status}>
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
      </FilterSection>
      <CatalogDraftsCard entries={catalogEntries} />
    {:else}
      {#each groupedSections as [group, keys] (group)}
        {@const title = sidebarDomain.FILTER_GROUPS[group]}
        {#if group === "libraries"}
          {@const label = sidebarDomain.FILTERS.libraries.label}
          {#if librariesQuery.isError}
            <FilterSection {label}>
              <p class="hint">{errorMessage(librariesQuery.error, "Failed to load libraries")}</p>
            </FilterSection>
          {:else if libraries.length > 1}
            <FilterSection {label}>
              {#snippet control()}
                <span class="hint"
                  >{filters.libraryIds.length === 0
                    ? "All libraries"
                    : `${filters.libraryIds.length} of ${libraries.length} selected`}</span
                >
              {/snippet}
              <CheckboxList
                options={libraries.map((library) => ({
                  value: library.id,
                  label: library.title,
                  count: library.count,
                }))}
                selected={filters.libraryIds}
                ontoggle={(id) => (draft.libraryIds = toggleSelectedValue(filters.libraryIds, id))}
              />
            </FilterSection>
          {/if}
        {:else if title}
          <FilterSection label={title}>
            {#each keys as key (key)}
              {@render filter(key)}
            {/each}
          </FilterSection>
        {:else}
          {#each keys as key (key)}
            <FilterSection label={sidebarDomain.FILTERS[key].label}>
              {@render filter(key)}
            </FilterSection>
          {/each}
        {/if}
      {/each}

      {#if uiState.sidebarMode === "collections" && openGroup && openGroup !== UNMANAGED_GROUP}
        {@const group = openGroup}
        <CollectionGroupActions
          {group}
          mediaType={uiState.sidebarTab}
          onrename={(replacement) => {
            uiState.collectionGroupChanged(group, replacement);
            openSidebarGroup(replacement);
          }}
          ondelete={() => {
            uiState.collectionGroupChanged(group, "");
            openSidebarGroup(null);
            uiState.closePopup();
          }}
        />
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
    <button class="btn btn-secondary footer-start" onclick={clear} disabled={bulkActionBusy}
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
