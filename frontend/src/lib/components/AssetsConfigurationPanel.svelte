<script lang="ts">
  import { THEME_SOURCE_LABELS } from "../../generated/settings";
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
  const hintId = $props.id();
</script>

<div class="option-card">
  <span class="form-label">Libraries</span>
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
    />
  </div>
  <SidebarItemsOption
    checked={config.useSidebarItems}
    sidebarItems={sidebarState.current}
    muted={!config.useSidebarItems && config.selectedLibraries.length > 0}
    onchange={(selected) => (config.useSidebarItems = selected)}
  />
</div>

<div class="option-card">
  <span class="form-label">Options</span>
  <label class="checkbox-group">
    <input type="checkbox" bind:checked={config.includeUnmonitored} />
    <span>Include unmonitored items</span>
  </label>
  <label class="checkbox-group">
    <input
      type="checkbox"
      bind:checked={config.overwriteExisting}
      aria-label="Overwrite existing"
      aria-describedby="{hintId}-overwrite"
    />
    <span>Overwrite existing</span>
    <span class="inline-hint" id="{hintId}-overwrite">Search again and replace files</span>
  </label>
  <label class="checkbox-group">
    <input
      type="checkbox"
      bind:checked={config.retrySavedDownloads}
      disabled={config.overwriteExisting}
      aria-label="Retry saved downloads"
      aria-describedby="{hintId}-retry"
    />
    <span>Retry saved downloads</span>
    <span class="inline-hint" id="{hintId}-retry">Missing files only</span>
  </label>
  <div class="form-row skip-row">
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
    <span class="inline-hint">0 = off</span>
  </div>
</div>

<ArtWorkflowCard {form} />

<WorkflowCard title="Themes" bind:enabled={config.enableThemes} --workflow-accent="var(--violet)">
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
  .checkbox-group {
    flex-wrap: wrap;
  }

  .inline-hint {
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: 400;
  }

  .muted {
    opacity: 0.5;
  }

  .skip-row {
    margin-bottom: 0;
    flex-wrap: wrap;
  }
</style>
