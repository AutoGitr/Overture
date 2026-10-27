<script lang="ts">
  import ArrowDownWideNarrow from "@lucide/svelte/icons/arrow-down-wide-narrow";
  import ArrowUpDown from "@lucide/svelte/icons/arrow-up-down";
  import ArrowUpNarrowWide from "@lucide/svelte/icons/arrow-up-narrow-wide";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Funnel from "@lucide/svelte/icons/funnel";
  import Search from "@lucide/svelte/icons/search";
  import X from "@lucide/svelte/icons/x";
  import {
    defaultSortDir,
    type MenuEntry,
    type SearchFieldGroup,
    type SidebarSearchField,
    type SidebarSortDir,
    type SidebarSortField,
  } from "../utils/sidebarDomain";
  import MenuButton from "./MenuButton.svelte";
  import MenuOption from "./MenuOption.svelte";

  let {
    section,
    searchGroups,
    placeholder,
    sortFields,
    filtersOpen,
    hasActiveFilters,
    searchQuery,
    searchField,
    sortField,
    sortDir,
    onOpenFilters,
    onSearchQueryChange,
    onSearchFieldChange,
    onSetSort,
  }: {
    /** Names the list shown, so menus close when it changes. */
    section: string;
    /** Search fields to choose from; a single field needs no menu. */
    searchGroups: SearchFieldGroup[];
    placeholder: string;
    /** Sort fields to choose from; none hides the sort menu and the filters. */
    sortFields: MenuEntry<SidebarSortField>[];
    filtersOpen: boolean;
    hasActiveFilters: boolean;
    searchQuery: string;
    searchField: SidebarSearchField;
    sortField: SidebarSortField;
    sortDir: SidebarSortDir;
    onOpenFilters: () => void;
    onSearchQueryChange: (value: string) => void;
    onSearchFieldChange: (field: SidebarSearchField) => void;
    onSetSort: (field: SidebarSortField, dir: SidebarSortDir) => void;
  } = $props();

  let searchInput: HTMLInputElement;

  let isDefaultSort = $derived(sortField === "title" && sortDir === "asc");
  let sortLabel = $derived(sortFields.find((entry) => entry.id === sortField)?.shortLabel);
  let searchOptions = $derived(
    searchGroups.reduce((count, group) => count + group.fields.length, 0),
  );

  function chooseSort(field: SidebarSortField) {
    onSetSort(
      field,
      sortField === field ? (sortDir === "asc" ? "desc" : "asc") : defaultSortDir(field),
    );
  }

  /** `/` outside a text field, or Ctrl/Cmd+K anywhere, jumps to the search box. */
  function focusSearchShortcut(event: KeyboardEvent) {
    if (event.defaultPrevented || event.altKey) return;
    const { target } = event;
    const shortcut =
      event.ctrlKey || event.metaKey
        ? event.key.toLowerCase() === "k"
        : event.key === "/" &&
          !(
            target instanceof HTMLElement &&
            (target.isContentEditable || target.matches("input, textarea, select"))
          );
    if (!shortcut) return;
    searchInput.focus({ preventScroll: true });
    // An open modal makes the sidebar inert; leave the key to the browser then.
    if (document.activeElement !== searchInput) return;
    event.preventDefault();
    searchInput.select();
  }
</script>

<svelte:window onkeydown={focusSearchShortcut} />

<div class="sidebar-controls">
  {#if sortFields.length}
    <button
      type="button"
      class={["btn btn-ghost btn-icon filter-btn", { "has-filter": hasActiveFilters }]}
      onclick={onOpenFilters}
      aria-label="Open filters"
      aria-haspopup="dialog"
      aria-expanded={filtersOpen}
      title="Filters"
    >
      <!-- A filled funnel marks active filters. -->
      <Funnel size={16} fill={hasActiveFilters ? "currentColor" : "none"} />
    </button>
  {/if}

  <div class="search-wrapper">
    {#if searchOptions > 1}
      <MenuButton
        label="Choose search field"
        title="Search by field"
        menuLabel="Search by"
        active={searchField !== "title"}
        attached
        resetKey={section}
      >
        {#snippet trigger()}
          <Search size={13} />
          <ChevronDown size={11} />
        {/snippet}
        {#snippet menu(close)}
          {#each searchGroups as group, index (group.label)}
            {#if index > 0}
              <div class="separator" role="separator"></div>
            {/if}
            <div role="group" aria-label={group.label}>
              <!-- Headings only matter once there is more than one group. -->
              {#if searchGroups.length > 1}
                <div class="group-label" aria-hidden="true">{group.label}</div>
              {/if}
              {#each group.fields as field (field.id)}
                <MenuOption
                  checked={searchField === field.id}
                  onselect={() => {
                    onSearchFieldChange(field.id);
                    close(false);
                    searchInput.focus({ preventScroll: true });
                  }}
                >
                  {field.label}
                </MenuOption>
              {/each}
            </div>
          {/each}
        {/snippet}
      </MenuButton>
    {/if}

    <input
      type="text"
      class="search-input"
      bind:this={searchInput}
      aria-label="Search sidebar"
      {placeholder}
      value={searchQuery}
      oninput={(event) => onSearchQueryChange(event.currentTarget.value)}
    />

    {#if searchQuery}
      <button
        type="button"
        class="search-clear-btn"
        aria-label="Clear search"
        title="Clear search"
        onclick={() => {
          onSearchQueryChange("");
          searchInput.focus({ preventScroll: true });
        }}
      >
        <X size={12} />
      </button>
    {:else}
      <kbd class="search-kbd" aria-hidden="true">/</kbd>
    {/if}
  </div>

  {#if sortFields.length}
    <MenuButton
      label="Choose sort order"
      title="Sort order"
      menuLabel="Sort by"
      active={!isDefaultSort}
      align="right"
      resetKey={section}
    >
      {#snippet trigger()}
        {#if isDefaultSort}
          <ArrowUpDown size={13} />
        {:else if sortDir === "asc"}
          <ArrowUpNarrowWide size={13} />
        {:else}
          <ArrowDownWideNarrow size={13} />
        {/if}
        {#if !isDefaultSort}
          <span class="sort-field-label">{sortLabel}</span>
        {/if}
      {/snippet}
      {#snippet menu(close)}
        {#each sortFields as field (field.id)}
          <MenuOption
            checked={sortField === field.id}
            onselect={() => {
              chooseSort(field.id);
              close(true);
            }}
          >
            <span>{field.label}</span>
            {#if sortField === field.id}
              <span class="sort-dir">{sortDir === "asc" ? "Asc" : "Desc"}</span>
            {/if}
          </MenuOption>
        {/each}
      {/snippet}
    </MenuButton>
  {/if}
</div>

<style>
  .sidebar-controls {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3);
    border-bottom: var(--border-subtle);
  }

  .filter-btn {
    position: relative;
    flex-shrink: 0;
  }

  .filter-btn.has-filter {
    color: var(--accent);
    background: var(--accent-muted);
    box-shadow: inset 0 0 0 1px var(--accent);
  }

  .sort-field-label {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--accent);
  }

  .group-label {
    padding: var(--space-2) var(--space-3) var(--space-1);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-tertiary);
  }

  .separator {
    margin: var(--space-1) 0;
    border-top: var(--border-subtle);
  }

  .sort-dir {
    margin-left: var(--space-2);
    font-size: 10px;
    color: var(--accent);
  }

  .search-wrapper {
    position: relative;
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--space-1);
    min-width: 0;
    padding: 0 var(--space-2) 0 0;
    overflow: visible;
    color: var(--text-tertiary);
    background: var(--field-bg);
    border: var(--border-muted);
    border-radius: var(--radius-sm);
  }

  .search-wrapper:focus-within {
    border-color: var(--accent);
    box-shadow: var(--focus-ring);
  }

  .search-clear-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    padding: 2px;
    color: var(--text-tertiary);
    cursor: pointer;
    background: transparent;
    border: none;
    border-radius: 50%;
  }

  .search-clear-btn:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .search-kbd {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 1px 5px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-tertiary);
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    line-height: 1.2;
    pointer-events: none;
    -webkit-user-select: none;
    user-select: none;
  }

  .search-input {
    flex: 1;
    min-width: 0;
    padding: var(--space-2) 0;
    color: var(--text-primary);
    font-size: var(--text-sm);
    background: transparent;
    border: none;
    outline: none;
  }

  .search-input:first-child {
    padding-left: var(--space-2);
  }

  .search-input:focus {
    box-shadow: none;
  }
</style>
