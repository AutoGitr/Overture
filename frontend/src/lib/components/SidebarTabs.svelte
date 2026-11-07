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
    <span class="icon" aria-hidden="true">
      <span class="current"><Icon size={16} /></span>
      {#if next}<span class="next"><next.Icon size={16} /></span>{/if}
    </span>
    <span class="label">{label}</span>
    <span class="count">{count}</span>
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
    container-type: inline-size;
    border-bottom: var(--border-subtle);
  }

  .tab {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-width: 0;
    padding: var(--space-3) var(--space-2);
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
    display: none;
  }

  @container (min-width: 440px) {
    .label {
      display: inline;
    }
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
