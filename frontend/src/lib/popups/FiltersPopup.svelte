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
  import { uiState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import {
    filterAvailableValues,
    selectedValuesForAll,
    toggleSelectedValue,
  } from "../utils/popupSelection";
  import { filterCatalogEntries } from "../utils/sidebarDomain";
  import { ART_SLOT_LABELS, ART_SOURCES, CATALOG_FILTER_KEYS, CATALOG_FILTER_LABELS, FILTERS, FILTER_GROUPS, type FilterGroup, type FilterKey, THEME_SOURCES, TMDB_FILTER_LABELS, defaultCatalogFilters, defaultTmdbFilters, filterSections, metadataIssuesFor, tmdbFilterKeysFor, withoutCatalogFilters } from "../utils/sidebarFilters";
  import { METADATA_ISSUES, SELECTED_ART_SOURCE_LABELS, THEME_ID_SOURCE_LABELS } from "../../generated/settings";
  import BulkOperationsCard from "../components/BulkOperationsCard.svelte";
  import CardColumn from "../components/CardColumn.svelte";
  import CatalogDraftsCard from "../components/CatalogDraftsCard.svelte";
  import CustomFilterCard from "../components/CustomFilterCard.svelte";
  import Checklist from "../components/Checklist.svelte";
  import LibraryOptions from "../components/LibraryOptions.svelte";
  import FieldRow from "../components/FieldRow.svelte";
  import PopupSection from "../components/PopupSection.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import RangeFields from "../components/RangeFields.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import Select from "../components/Select.svelte";
  import type { SelectOption } from "../utils/selectOptions";
  import { SectionView, setSectionView } from "../stores/sectionState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { alphabetical } from "../utils/alphabetical";
  import { keysOf } from "../utils/records";
  import { COLLECTION_POSTER_OPTIONS } from "../utils/collectionPosters";
  import { filterState, defaultFilters, type FilterState } from "../stores/filterState.svelte";

  // Its sections stay as the user left them across visits and reloads.
  setSectionView(new SectionView(() => true, "filters"));
  const id = $props.id();
  const catalogBrowsing = new CatalogBrowsing();
  let catalogEnabled = $derived(catalogBrowsing.enabled);

  let draft = $state<FilterState>($state.snapshot(filterState.current));

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
  /** The art the art filters can look at: season posters only a show's. */
  let artFilterSlots = $derived([
    ["any", "Any art"] as const,
    ...keysOf(ART_SLOT_LABELS)
      .filter(
        (slot) =>
          slot !== "season_posters" ||
          (uiState.sidebarMode === "items" && uiState.sidebarTab === "show"),
      )
      .map((slot) => [slot, ART_SLOT_LABELS[slot]] as const),
  ]);
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
  const SELECTIONS_OPTIONS = [
    ["all", "All"],
    ["matching", "Matching"],
    ["different", "Different"],
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
    seasonPosters: { options: COMPLETE_OPTIONS },
    overtureDb: { options: COMPLETE_OPTIONS },
    themerrDb: { options: COMPLETE_OPTIONS },
    catalogPoster: { options: SELECTIONS_OPTIONS },
    catalogBackground: { options: SELECTIONS_OPTIONS },
    catalogSeasonPosters: { options: SELECTIONS_OPTIONS },
    catalogTheme: { options: SELECTIONS_OPTIONS },
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
  let collectionOptions = $derived<SelectOption<number | null>[]>([
    { value: null, label: "Any collection" },
    ...collections.map((row) => ({ value: row.id, label: row.title })),
  ]);
  let metadataIssueOptions = $derived(
    metadataIssuesFor(uiState.sidebarTab, catalogEnabled, uiState.sidebarMode),
  );
  let groupedSections = $derived.by(() => {
    const shown = filterSections(uiState.sidebarMode, {
      tab: uiState.sidebarTab,
      catalogEnabled,
      smart: !!capabilities.data?.smart,
      collections: settingsState.current.collections_supported,
    });
    return (Object.keys(FILTER_GROUPS) as FilterGroup[])
      .map((group) => [group, shown.filter((key) => FILTERS[key].group === group)] as const)
      .filter(([, keys]) => keys.length > 0);
  });

  /** Splits *keys* into runs of neighbours offering the same choices. */
  function choiceRuns(keys: readonly FilterKey[]): FilterKey[][] {
    const runs: FilterKey[][] = [];
    for (const key of keys) {
      const run = runs.at(-1);
      const previous = run?.at(-1);
      if (run && previous && choicesOf(previous) === choicesOf(key)) run.push(key);
      else runs.push([key]);
    }
    return runs;
  }

  function choicesOf(key: FilterKey) {
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

  let catalogDraft = $state($state.snapshot(filterState.catalog));
  let catalogPosters = $state(uiState.catalogPosters);
  let tmdbDraft = $state($state.snapshot(filterState.tmdb));
  let tmdbFilterKeys = $derived(
    tmdbFilterKeysFor(uiState.sidebarSource, uiState.sidebarMode, catalogEnabled),
  );
  const catalogQuery = createQuery(() => ({
    ...listCatalogEntriesOptions({
      query:
        uiState.sidebarMode === "collections"
          ? { media_type: "collection", posters: catalogPosters }
          : { media_type: uiState.sidebarTab },
    }),
    enabled: uiState.sidebarSource === "overturedb",
  }));
  /** The entries the draft filters and the search match, as the sidebar would list them. */
  let catalogEntries = $derived(
    filterCatalogEntries({
      entries: catalogQuery.data ?? [],
      filters: catalogDraft,
      searchQuery: uiState.searchQuery,
      searchField: uiState.searchField,
    }),
  );

  /** Nothing differs from the filters in use, so Apply would change nothing. */
  let unchanged = $derived(
    uiState.searchingTmdb
      ? JSON.stringify(tmdbDraft) === JSON.stringify(filterState.tmdb)
      : uiState.sidebarSource === "overturedb"
      ? JSON.stringify(catalogDraft) === JSON.stringify(filterState.catalog) &&
        catalogPosters === uiState.catalogPosters
      : JSON.stringify(filters) === JSON.stringify(filterState.current),
  );

  function apply() {
    if (uiState.searchingTmdb) {
      filterState.tmdb = $state.snapshot(tmdbDraft);
      uiState.closePopup();
      return;
    }
    if (uiState.sidebarSource === "overturedb") {
      filterState.catalog = $state.snapshot(catalogDraft);
      uiState.setCatalogPosters(catalogPosters);
      uiState.closePopup();
      return;
    }
    const applied = $state.snapshot(filters);
    filterState.set(
      catalogEnabled ? applied : withoutCatalogFilters(applied, defaultFilters()),
    );
    uiState.closePopup();
  }

  function clear() {
    draft = defaultFilters();
    catalogDraft = defaultCatalogFilters();
    tmdbDraft = defaultTmdbFilters();
  }
</script>

{#snippet filter(key: FilterKey)}
  {@const label = FILTERS[key].label}
  {#if key === "resolution"}
    <FieldRow {label}>
      <SegmentedControl
        label="Resolution art type"
        options={artFilterSlots}
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
        options={artFilterSlots}
        bind:value={draft.artSource.artType}
      />
    </FieldRow>
    <Checklist
      label="Sources"
      groups={[
        {
          key,
          label: "",
          options: ART_SOURCES.map((source) => ({
            id: source,
            label: SELECTED_ART_SOURCE_LABELS[source],
            checked: draft.artSource.sources.includes(source),
          })),
        },
      ]}
      ontoggle={(_key, source) =>
        (draft.artSource.sources = toggleSelectedValue(draft.artSource.sources, source))}
      ontoggleall={(checked) =>
        (draft.artSource.sources = selectedValuesForAll(checked, ART_SOURCES))}
    />
  {:else if key === "collection"}
    <FieldRow {label} for={`${id}-collection`}>
      <Select
        id={`${id}-collection`}
        options={collectionOptions}
        bind:value={() => filters.collectionId, (next) => (draft.collectionId = next)}
      />
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
    <Checklist
      {label}
      groups={[
        {
          key,
          label: "",
          options: THEME_SOURCES.map((source) => ({
            id: source,
            label: THEME_ID_SOURCE_LABELS[source],
            checked: draft.themeSources.includes(source),
          })),
        },
      ]}
      ontoggle={(_key, source) =>
        (draft.themeSources = toggleSelectedValue(draft.themeSources, source))}
      ontoggleall={(checked) => (draft.themeSources = selectedValuesForAll(checked, THEME_SOURCES))}
    />
  {:else if key === "metadataIssues"}
    <FieldRow label="Match">
      <SegmentedControl
        label="Metadata issues match mode"
        options={MATCH_MODE_OPTIONS}
        bind:value={draft.metadataIssues.mode}
      />
    </FieldRow>
    <Checklist
      label="Issues"
      groups={[
        {
          key,
          label: "",
          options: metadataIssueOptions.map((flag) => ({
            id: flag,
            label: METADATA_ISSUES[flag].label,
            checked: draft.metadataIssues.flags.includes(flag),
          })),
        },
      ]}
      ontoggle={(_key, flag) =>
        (draft.metadataIssues.flags = toggleSelectedValue(draft.metadataIssues.flags, flag))}
      ontoggleall={(checked) =>
        (draft.metadataIssues.flags = selectedValuesForAll(checked, metadataIssueOptions))}
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

<PopupShell title="Filters & operations" size="wide" onclose={() => uiState.closePopup()}>
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
    {#if uiState.searchingTmdb}
      <PopupSection label="TMDB results">
        {#each tmdbFilterKeys as key (key)}
          <FieldRow label={TMDB_FILTER_LABELS[key]}>
            <SegmentedControl
              label={TMDB_FILTER_LABELS[key]}
              options={MEDIA_SERVER_OPTIONS}
              bind:value={tmdbDraft[key]}
            />
          </FieldRow>
        {/each}
      </PopupSection>
    {:else if uiState.sidebarSource === "overturedb"}
      <PopupSection label={FILTER_GROUPS.status}>
        {#if uiState.sidebarMode === "collections"}
          <FieldRow label="Poster style">
            <SegmentedControl
              label="Poster style"
              options={COLLECTION_POSTER_OPTIONS}
              bind:value={catalogPosters}
            />
          </FieldRow>
        {/if}
        {#each CATALOG_FILTER_KEYS as key (key)}
          {#if key !== "seasonPosters" || uiState.sidebarTab === "show"}
            <FieldRow label={CATALOG_FILTER_LABELS[key]}>
              <SegmentedControl
                label={CATALOG_FILTER_LABELS[key]}
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
        {@const title = FILTER_GROUPS[group]}
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
              <PopupSection label={FILTERS[key].label}>
                {@render filter(key)}
              </PopupSection>
            {:else if librariesQuery.isError}
              <PopupSection label={FILTERS.libraries.label}>
                <p class="hint">{errorMessage(librariesQuery.error, "Failed to load libraries")}</p>
              </PopupSection>
            {:else if libraries.length > 1}
              <PopupSection
                label={FILTERS.libraries.label}
                description={filters.libraryIds.length === 0
                  ? "All libraries"
                  : `${filters.libraryIds.length} of ${libraries.length} selected`}
              >
                <LibraryOptions
                  {libraries}
                  selected={filters.libraryIds}
                  ontoggle={(id) =>
                    (draft.libraryIds = toggleSelectedValue(filters.libraryIds, id))}
                  ontoggleall={(checked) =>
                    (draft.libraryIds = selectedValuesForAll(
                      checked,
                      libraries.map((library) => library.id),
                    ))}
                />
              </PopupSection>
            {/if}
          {/each}
        {/if}
        {#if group === "libraries" && uiState.sidebarMode === "items"}
          <CustomFilterCard
            bind:filterId={draft.customFilter}
            mediaType={uiState.sidebarTab}
          />
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
