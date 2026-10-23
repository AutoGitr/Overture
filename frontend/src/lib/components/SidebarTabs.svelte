<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import { goToCatalog, goToCollectionsList, goToLibrary } from "../router/routes";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import type { SidebarSource, SidebarTab } from "../utils/sidebarDomain";

  let {
    totalMovies,
    totalShows,
    datasetEnabled = false,
  }: { totalMovies: number; totalShows: number; datasetEnabled?: boolean } = $props();

  let collectionsEnabled = $derived(
    uiState.sidebarSource === "overturedb"
      ? uiState.sidebarTab === "movie"
      : settingsState.current.collections_supported,
  );
  function switchSource(source: SidebarSource) {
    uiState.mobileShowDetail = false;
    if (source === "overturedb") goToCatalog(uiState.sidebarTab, uiState.sidebarMode);
    else if (uiState.sidebarMode === "collections" && settingsState.current.collections_supported)
      goToCollectionsList(uiState.sidebarTab);
    else goToLibrary(uiState.sidebarTab);
  }
  function switchMode(collections: boolean) {
    uiState.mobileShowDetail = false;
    if (uiState.sidebarSource === "overturedb")
      goToCatalog(uiState.sidebarTab, collections ? "collections" : "items");
    else if (collections) goToCollectionsList(uiState.sidebarTab);
    else goToLibrary(uiState.sidebarTab);
  }
  function switchTab(tab: SidebarTab) {
    // A top-level tab switch is a request to browse that library: keep the
    // browser surface visible on mobile while the matching route settles.
    uiState.mobileShowDetail = false;
    if (uiState.sidebarSource === "overturedb") goToCatalog(tab);
    else goToLibrary(tab);
  }
</script>

{#snippet tab(value: SidebarTab, label: string, count: number)}
  <button
    type="button"
    class={["tab", { active: uiState.sidebarTab === value }]}
    aria-pressed={uiState.sidebarTab === value}
    onclick={() => switchTab(value)}
  >
    {#if value === "movie"}
      <Clapperboard size={16} />
    {:else}
      <MonitorPlay size={16} />
    {/if}
    <span>{label}</span>
    <span class="count">{count}</span>
  </button>
{/snippet}

{#if datasetEnabled}
  <SegmentedControl
    label="Sidebar source"
    options={[
      ["library", "Library"],
      ["overturedb", "OvertureDB"],
    ] as const}
    bind:value={() => uiState.sidebarSource, switchSource}
  />
{/if}

<div class="tabs">
  {@render tab("movie", "Movies", totalMovies)}
  {@render tab("show", "Shows", totalShows)}
</div>

{#if collectionsEnabled}
  <div class="modes">
    <button
      type="button"
      class={["mode", { active: uiState.sidebarMode === "items" }]}
      aria-pressed={uiState.sidebarMode === "items"}
      onclick={() => switchMode(false)}>Items</button
    >
    <button
      type="button"
      class={["mode", { active: uiState.sidebarMode === "collections" }]}
      aria-pressed={uiState.sidebarMode === "collections"}
      onclick={() => switchMode(true)}>Collections</button
    >
  </div>
{/if}

<style>
  .tabs {
    display: flex;
    border-bottom: var(--border-subtle);
  }

  .tab {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-tertiary);
    border-bottom: 2px solid transparent;
  }

  .tab:hover {
    color: var(--text-secondary);
    background: var(--bg-secondary);
  }

  .tab.active {
    color: var(--text-primary);
    border-bottom-color: var(--accent);
  }

  .count {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    background: var(--bg-tertiary);
    padding: 1px 6px;
    border-radius: var(--radius-full);
    color: var(--text-secondary);
  }

  .modes {
    display: flex;
    background: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    padding: 2px;
  }

  .mode {
    flex: 1;
    border: none;
    background: transparent;
    color: var(--text-tertiary);
    font-size: var(--text-xs);
    font-weight: 500;
    padding: var(--space-1) 0;
    border-radius: calc(var(--radius-sm) - 2px);
    cursor: pointer;
  }

  .mode:hover {
    color: var(--text-primary);
  }

  .mode.active {
    background: var(--bg-primary);
    color: var(--text-primary);
    box-shadow: var(--shadow-sm);
  }
</style>
