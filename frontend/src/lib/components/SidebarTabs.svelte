<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import type { CollectionView, SidebarTab } from "../utils/sidebarDomain";

  let { totalMovies, totalShows }: { totalMovies: number; totalShows: number } = $props();

  let collectionsEnabled = $derived(
    uiState.sidebarSource === "overturedb"
      ? uiState.sidebarTab === "movie"
      : settingsState.current.collections_supported,
  );

  /** Show the library's collections in *view*; the open collection stays open. */
  function showCollections(view: CollectionView) {
    uiState.setCollectionView(view);
    if (uiState.sidebarMode !== "collections")
      uiState.goToSection(uiState.sidebarSource, uiState.sidebarTab, "collections");
  }

  let collections = $derived(uiState.sidebarMode === "collections");
  let modes = $derived([
    {
      label: "Items",
      active: !collections,
      select: () => uiState.goToSection(uiState.sidebarSource, uiState.sidebarTab, "items"),
    },
    // The catalog's collections have no groups.
    ...(uiState.sidebarSource === "library"
      ? (["groups", "collections"] as const).map((view) => ({
          label: view === "groups" ? "Groups" : "Collections",
          active: collections && uiState.collectionView === view,
          select: () => showCollections(view),
        }))
      : [
          {
            label: "Collections",
            active: collections,
            select: () => uiState.goToSection("overturedb", uiState.sidebarTab, "collections"),
          },
        ]),
  ]);
</script>

{#snippet tab(value: SidebarTab, label: string, count: number)}
  <button
    type="button"
    class={["tab", { active: uiState.sidebarTab === value }]}
    aria-pressed={uiState.sidebarTab === value}
    onclick={() => uiState.goToSection(uiState.sidebarSource, value, "items")}
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

<div class="tabs">
  {@render tab("movie", "Movies", totalMovies)}
  {@render tab("show", "Shows", totalShows)}
</div>

{#if collectionsEnabled}
  <div class="modes" role="group" aria-label="Show">
    {#each modes as option (option.label)}
      <button
        type="button"
        class={["mode", { active: option.active }]}
        aria-pressed={option.active}
        onclick={option.select}>{option.label}</button
      >
    {/each}
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
