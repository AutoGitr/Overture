<script lang="ts">
  import type { ArtType, LibrarySectionRead, RecentUnit } from "../../generated/rest/types.gen";
  import type { AssetsConfig } from "../utils/assetsPopup";
  import type { SidebarTab } from "../utils/sidebarDomain";
  import { disabledSources } from "../utils/assetsPopup";
  import ArtWorkflowCard from "./ArtWorkflowCard.svelte";
  import LibraryChecklist from "./LibraryChecklist.svelte";
  import SidebarItemsOption from "./SidebarItemsOption.svelte";
  import ThemeWorkflowCard from "./ThemeWorkflowCard.svelte";

  let {
    config,
    movieLibraries,
    showLibraries,
    useSidebarItems,
    sidebarItems,
    onusesidebaritemschange,
    onincludeunmonitoredchange,
    onoverwriteexistingchange,
    onretrysaveddownloadschange,
    librariesLoading,
    librariesError,
    onretrylibraries,
    publicDatasetEnabled,
    publicDatasetStatusError,
    hasSelectedLibraries,
    hasShowLibraries,
    localArtMatchingEnabled,
    ontogglelibrary,
    ontoggleall,
    ontoggletype,
    ontoggleartsource,
    ontogglethemesource,
    onmoveartsource,
    onmovethemesource,
    onthresholdchange,
    onenableartchange,
    onenablethemeschange,
    onskiprecentvalchange,
    onskiprecentunitchange,
  }: {
    /** Read-only here: every change is reported back through a callback. */
    config: AssetsConfig;
    movieLibraries: LibrarySectionRead[];
    showLibraries: LibrarySectionRead[];
    useSidebarItems: boolean;
    sidebarItems: { type: SidebarTab; itemIds: number[] } | null;
    onusesidebaritemschange: (selected: boolean) => void;
    onincludeunmonitoredchange: (selected: boolean) => void;
    onoverwriteexistingchange: (selected: boolean) => void;
    onretrysaveddownloadschange: (selected: boolean) => void;
    librariesLoading: boolean;
    librariesError: string;
    onretrylibraries: () => void;
    publicDatasetEnabled: boolean;
    publicDatasetStatusError: string;
    hasSelectedLibraries: boolean;
    hasShowLibraries: boolean;
    localArtMatchingEnabled: boolean;
    ontogglelibrary: (id: string) => void;
    ontoggleall: (checked: boolean) => void;
    ontoggletype: (type: ArtType) => void;
    ontoggleartsource: (source: string) => void;
    ontogglethemesource: (source: string) => void;
    onmoveartsource: (source: string, target: string) => void;
    onmovethemesource: (source: string, target: string) => void;
    onthresholdchange: (value: number) => void;
    onenableartchange: (enabled: boolean) => void;
    onenablethemeschange: (enabled: boolean) => void;
    onskiprecentvalchange: (value: number) => void;
    onskiprecentunitchange: (unit: RecentUnit) => void;
  } = $props();
</script>

<div class="option-card">
  <span class="form-label">Libraries</span>
  <div class:muted={useSidebarItems}>
    <LibraryChecklist
      {movieLibraries}
      {showLibraries}
      selectedIds={useSidebarItems ? [] : config.selectedLibraries}
      loading={librariesLoading}
      error={librariesError}
      onretry={onretrylibraries}
      emptyMessage="No synced libraries found. Run Sync first."
      ontoggle={ontogglelibrary}
      {ontoggleall}
    />
  </div>
  <SidebarItemsOption
    checked={useSidebarItems}
    {sidebarItems}
    muted={!useSidebarItems && config.selectedLibraries.length > 0}
    onchange={onusesidebaritemschange}
  />
</div>

<div class="option-card">
  <span class="form-label">Options</span>
  <p class="option-note">
    By default, anything that already has a file or a saved choice is skipped.
  </p>
  <label class="checkbox-group">
    <input
      type="checkbox"
      checked={config.includeUnmonitored}
      onchange={(event) => onincludeunmonitoredchange(event.currentTarget.checked)}
    />
    <span>Include unmonitored items</span>
  </label>
  <label class="checkbox-group">
    <input
      type="checkbox"
      checked={config.overwriteExisting}
      onchange={(event) => onoverwriteexistingchange(event.currentTarget.checked)}
    />
    <span>Overwrite existing</span>
  </label>
  <p class="option-note">Searches again and replaces existing files.</p>
  <label class="checkbox-group">
    <input
      type="checkbox"
      checked={config.retrySavedDownloads}
      disabled={config.overwriteExisting}
      onchange={(event) => onretrysaveddownloadschange(event.currentTarget.checked)}
    />
    <span>Retry saved downloads</span>
  </label>
  <p class="option-note">Downloads saved choices again where the file is missing.</p>
</div>

<div class="option-card">
  <span class="form-label">Workflows</span>
  <div class="filter-options">
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={config.enableArt}
        onchange={(event) => onenableartchange((event.currentTarget as HTMLInputElement).checked)}
      />
      <span>Art</span>
    </label>
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={config.enableThemes}
        onchange={(event) =>
          onenablethemeschange((event.currentTarget as HTMLInputElement).checked)}
      />
      <span>Themes</span>
    </label>
  </div>
</div>

{#if config.enableArt}
  <ArtWorkflowCard
    artTypes={config.artTypes}
    {hasSelectedLibraries}
    {hasShowLibraries}
    artSourceOrder={config.artSourceOrder}
    selectedArtSources={config.selectedArtSources}
    disabledSources={disabledSources(publicDatasetEnabled)}
    threshold={config.threshold}
    {localArtMatchingEnabled}
    {ontoggletype}
    ontogglesource={ontoggleartsource}
    onmovesource={onmoveartsource}
    {onthresholdchange}
  />
{/if}

{#if config.enableThemes}
  <ThemeWorkflowCard
    themeSourceOrder={config.themeSourceOrder}
    selectedThemeSources={config.selectedThemeSources}
    disabledSources={disabledSources(publicDatasetEnabled)}
    ontogglesource={ontogglethemesource}
    onmovesource={onmovethemesource}
  />
{/if}

{#if publicDatasetStatusError}
  <div class="option-error">{publicDatasetStatusError}</div>
{/if}

<div class="option-card">
  <span class="form-label">Skip recently checked</span>
  <div class="form-row skip-row">
    <span class="form-label">Within:</span>
    <input
      type="number"
      class="number-input"
      min="0"
      value={config.skipRecentVal}
      oninput={(event) =>
        onskiprecentvalchange(Number((event.currentTarget as HTMLInputElement).value) || 0)}
    />
    <select
      value={config.skipRecentUnit}
      onchange={(event) =>
        onskiprecentunitchange((event.currentTarget as HTMLSelectElement).value as RecentUnit)}
    >
      <option value="hours">hours</option>
      <option value="days">days</option>
    </select>
  </div>
  <div class="option-note">
    Skips items whose sources were searched this recently. 0 turns it off.
  </div>
</div>

<style>
  .muted {
    opacity: 0.5;
  }

  .filter-options {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-4);
    margin-top: var(--space-2);
  }

  .skip-row {
    margin-bottom: 0;
    flex-wrap: wrap;
  }
</style>
