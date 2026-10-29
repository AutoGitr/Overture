<script lang="ts">
  import { THEME_SOURCE_LABELS } from "../../generated/settings";
  import { settingsState } from "../stores/settingsState.svelte";
  import { sidebarState } from "../stores/sidebarState.svelte";
  import type { AssetsForm } from "../utils/assetsForm.svelte";
  import ArtWorkflowCard from "./ArtWorkflowCard.svelte";
  import LibraryChecklist from "./LibraryChecklist.svelte";
  import SidebarItemsOption from "./SidebarItemsOption.svelte";
  import SourceOrderList from "./SourceOrderList.svelte";
  import WorkflowCard from "./WorkflowCard.svelte";
  import WorkflowSection from "./WorkflowSection.svelte";

  let {
    form,
    librariesLoading,
    librariesError,
    onretrylibraries,
    publicDatasetStatusError,
  }: {
    form: AssetsForm;
    librariesLoading: boolean;
    librariesError: string;
    onretrylibraries: () => void;
    publicDatasetStatusError: string;
  } = $props();

  let config = $derived(form.config);
  /** The checklist entry for every collection, apart from the group names. */
  const ALL_COLLECTIONS = "\u0000all";
</script>

<div class="option-card">
  <div class={{ muted: config.useSidebarItems }}>
    <LibraryChecklist
      movieLibraries={form.movieLibraries}
      showLibraries={form.showLibraries}
      selectedIds={config.useSidebarItems ? [] : config.selectedLibraries}
      loading={librariesLoading}
      error={librariesError}
      onretry={onretrylibraries}
      emptyMessage="No synced libraries found. Run Sync first."
      ontoggle={(id) => form.toggleLibrary(id)}
      ontoggleall={(checked) => form.toggleAll(checked)}
      collections={settingsState.current.collections_supported
        ? [
            {
              id: ALL_COLLECTIONS,
              label: "All collections",
              checked: !config.useSidebarItems && config.allCollections,
            },
            ...form.collectionGroupOptions.map((group) => ({
              id: group,
              label: group,
              checked:
                !config.useSidebarItems && form.selectedCollectionGroups.includes(group),
            })),
          ]
        : undefined}
      oncollectiontoggle={(id) => form.toggleCollections(id === ALL_COLLECTIONS ? null : id)}
      oncollectionsall={(checked) => {
        if (checked !== config.allCollections) form.toggleCollections(null);
      }}
    />
  </div>
  <SidebarItemsOption
    checked={config.useSidebarItems}
    sidebarItems={sidebarState.current}
    collectionIds={sidebarState.collections?.collectionIds}
    muted={!config.useSidebarItems && config.selectedLibraries.length > 0}
    onchange={(selected) => (config.useSidebarItems = selected)}
  />
</div>

<div class="option-card">
  <span class="form-label">Options</span>
  <div class="filter-options">
    <label class="checkbox-group">
      <input type="checkbox" bind:checked={config.includeUnmonitored} />
      <span>Include unmonitored items</span>
    </label>
    <label
      class="checkbox-group"
      title="Search sources again and replace files; identical files are left untouched"
    >
      <input type="checkbox" bind:checked={config.overwriteExisting} />
      <span>Replace existing</span>
    </label>
  </div>
  <div class="form-row skip-row" title="0 checks every item">
    <span>Skip items checked within</span>
    <input
      type="number"
      class="number-input"
      aria-label="Skip items checked within"
      min="0"
      value={config.skipRecentVal}
      oninput={(event) => (config.skipRecentVal = Number(event.currentTarget.value) || 0)}
    />
    <select bind:value={config.skipRecentUnit} aria-label="Skip window unit">
      <option value="hours">hours</option>
      <option value="days">days</option>
    </select>
  </div>
</div>

<ArtWorkflowCard {form} />

<WorkflowCard title="Themes" kind="theme" bind:enabled={config.enableThemes}>
  {#if form.collectionScope}
    <p class="hint">Collection themes use OvertureDB and ThemerrDB, never a YouTube search.</p>
  {/if}
  <WorkflowSection label="Sources" note="First match wins, top to bottom.">
    <SourceOrderList
      sourceOrder={config.themeSourceOrder}
      selectedSources={config.selectedThemeSources}
      labels={THEME_SOURCE_LABELS}
      disabledSources={form.disabledSources}
      storageKey="theme"
      ontoggle={(source) => form.toggleThemeSource(source)}
      onmove={(source, target) => form.moveThemeSource(source, target)}
    />
  </WorkflowSection>
</WorkflowCard>

{#if publicDatasetStatusError}
  <div class="option-error">{publicDatasetStatusError}</div>
{/if}

<style>
  .muted {
    opacity: 0.5;
  }

  .skip-row {
    flex-wrap: wrap;
  }
</style>
