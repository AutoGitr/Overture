<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import Layers from "@lucide/svelte/icons/layers";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import type { CollectionView, SidebarTab } from "../utils/sidebarDomain";

  let {
    totalMovies,
    totalShows,
    totalCollections,
  }: { totalMovies: number; totalShows: number; totalCollections: number } = $props();

  let collections = $derived(uiState.sidebarMode === "collections");
  let library = $derived(uiState.sidebarSource === "library");
  /** Library collections hold movies and shows alike, so they sit beside both tabs. */
  let collectionsTab = $derived(library && settingsState.current.collections_supported);
  let catalogModes = $derived(!library && uiState.sidebarTab === "movie");

  /** Show the library's collections in *view*; the open collection stays open. */
  function showCollections(view: CollectionView) {
    uiState.setCollectionView(view);
    if (!collections) uiState.goToSection("library", uiState.sidebarTab, "collections");
  }

  let modes = $derived(
    library
      ? (["groups", "collections"] as const).map((view) => ({
          label: view === "groups" ? "Groups" : "Collections",
          active: uiState.collectionView === view,
          select: () => showCollections(view),
        }))
      : [
          {
            label: "Items",
            active: !collections,
            select: () => uiState.goToSection("overturedb", uiState.sidebarTab, "items"),
          },
          {
            label: "Collections",
            active: collections,
            select: () => uiState.goToSection("overturedb", uiState.sidebarTab, "collections"),
          },
        ],
  );
</script>

{#snippet tab(value: SidebarTab, label: string, count: number)}
  <button
    type="button"
    class={["tab", { active: uiState.sidebarTab === value && !(library && collections) }]}
    aria-pressed={uiState.sidebarTab === value && !(library && collections)}
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
  {#if collectionsTab}
    <button
      type="button"
      class={["tab", { active: collections }]}
      aria-pressed={collections}
      onclick={() => showCollections(uiState.collectionView)}
    >
      <Layers size={16} />
      <span>Collections</span>
      <span class="count">{totalCollections}</span>
    </button>
  {/if}
</div>

{#if (library && collections && collectionsTab) || catalogModes}
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
