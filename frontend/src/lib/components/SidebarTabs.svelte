<script lang="ts">
  import Folder from "@lucide/svelte/icons/folder";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { MEDIA_ICONS, type MediaIcon } from "../utils/mediaIcons";
  import type { SidebarTab } from "../utils/sidebarDomain";

  let {
    totalMovies,
    totalShows,
    totalCollections,
  }: {
    totalMovies: number;
    totalShows: number;
    /** How many rows the collections tab lists: groups in the groups view, else collections. */
    totalCollections: number;
  } = $props();

  let collections = $derived(uiState.sidebarMode === "collections");
  let library = $derived(uiState.sidebarSource === "library");
  let collectionsButton = $derived(
    library ? settingsState.current.collections_supported : uiState.sidebarTab === "movie",
  );
  let groups = $derived(library && uiState.collectionView === "groups");
  /** The open collections tab of the library toggles between its two views. */
  let toggles = $derived(library && collections);

  function openCollections() {
    if (!collections) uiState.goToSection(uiState.sidebarSource, uiState.sidebarTab, "collections");
    else if (library) uiState.setCollectionView(groups ? "collections" : "groups");
  }
</script>

{#snippet tab(
  Icon: MediaIcon | typeof Folder,
  label: string,
  count: number,
  active: boolean,
  onclick: () => void,
  next: { Icon: typeof Folder; label: string } | null = null,
)}
  <button
    type="button"
    class={["tab", { active, toggles: next !== null }]}
    aria-pressed={active}
    aria-label={next ? `${label} (${count}): show ${next.label.toLowerCase()}` : `${label} (${count})`}
    title={next ? `Showing ${label.toLowerCase()}, click to show ${next.label.toLowerCase()}` : label}
    {onclick}
  >
    <span class="label">{label}</span>
    <span class="summary">
      <span class="icon" aria-hidden="true">
        <span class="current"><Icon size={15} /></span>
        {#if next}<span class="next"><next.Icon size={15} /></span>{/if}
      </span>
      <span class="count">{count}</span>
    </span>
  </button>
{/snippet}

{#snippet itemsTab(value: SidebarTab, label: string, count: number)}
  {@render tab(MEDIA_ICONS[value], label, count, uiState.sidebarTab === value && !collections, () =>
    uiState.goToSection(uiState.sidebarSource, value, "items"),
  )}
{/snippet}

<div class="tabs">
  {@render itemsTab("movie", "Movies", totalMovies)}
  {@render itemsTab("show", "Shows", totalShows)}
  {#if collectionsButton}
    {@const collectionsView = { Icon: MEDIA_ICONS.collection, label: "Collections" }}
    {@const groupsView = { Icon: Folder, label: "Groups" }}
    {@const shown = groups ? groupsView : collectionsView}
    {@render tab(
      shown.Icon,
      shown.label,
      totalCollections,
      collections,
      openCollections,
      toggles ? (groups ? collectionsView : groupsView) : null,
    )}
  {/if}
</div>

<style>
  .tabs {
    display: grid;
    grid-auto-columns: 1fr;
    grid-auto-flow: column;
    border-bottom: var(--border-subtle);
  }

  /* Two fixed rows fit the widest label and a five-digit count in a third of
     the narrowest sidebar, so every tab shows all three at any width. */
  .tab {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    min-width: 0;
    padding: var(--space-2) var(--space-1);
    font-size: var(--text-xs);
    font-weight: 500;
    line-height: 1.2;
    color: var(--text-tertiary);
    border-bottom: 2px solid transparent;
  }

  .summary {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }

  .tab:hover {
    color: var(--text-secondary);
    background: var(--bg-secondary);
  }

  .tab.active {
    color: var(--text-primary);
    border-bottom-color: var(--accent);
  }

  .icon {
    display: grid;
  }

  .icon > * {
    grid-area: 1 / 1;
    display: flex;
  }

  /* A toggling tab previews the view it switches to. */
  .next,
  .toggles:is(:hover, :focus-visible) .current {
    visibility: hidden;
  }

  .toggles:is(:hover, :focus-visible) .next {
    visibility: visible;
  }

  .label {
    white-space: nowrap;
  }

  .count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    color: var(--text-secondary);
  }

  .active .count {
    color: var(--accent);
  }
</style>
