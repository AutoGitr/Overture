<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import Folder from "@lucide/svelte/icons/folder";
  import Layers from "@lucide/svelte/icons/layers";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import type { SidebarTab } from "../utils/sidebarDomain";

  let {
    totalMovies,
    totalShows,
    totalCollections,
  }: { totalMovies: number; totalShows: number; totalCollections: number } = $props();

  let collections = $derived(uiState.sidebarMode === "collections");
  let library = $derived(uiState.sidebarSource === "library");
  let collectionsButton = $derived(
    library ? settingsState.current.collections_supported : uiState.sidebarTab === "movie",
  );
  let groups = $derived(library && uiState.collectionView === "groups");
  let collectionsLabel = $derived(
    library && collections ? `Show ${groups ? "collections" : "groups"}` : "Collections",
  );

  function openCollections() {
    if (!collections) uiState.goToSection(uiState.sidebarSource, uiState.sidebarTab, "collections");
    else if (library) uiState.setCollectionView(groups ? "collections" : "groups");
  }
</script>

{#snippet tab(value: SidebarTab, label: string, count: number)}
  {@const active = uiState.sidebarTab === value && !collections}
  <button
    type="button"
    class={["tab", { active }]}
    aria-pressed={active}
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
  {#if collectionsButton}
    <button
      type="button"
      class={["tab", "collections", { active: collections }]}
      aria-pressed={collections}
      aria-label={collectionsLabel}
      title={library ? `${collectionsLabel} (${totalCollections})` : collectionsLabel}
      onclick={openCollections}
    >
      {#if groups}
        <Folder size={16} />
      {:else}
        <Layers size={16} />
      {/if}
    </button>
  {/if}
</div>

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

  .collections {
    flex: 0 0 auto;
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
</style>
