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
    searchFieldGroups,
    SIDEBAR_SEARCH_FIELDS,
    SIDEBAR_SORT_FIELDS,
    SIDEBAR_SORT_OPTIONS,
    type SidebarMode,
    type SidebarSearchField,
    type SidebarSortDir,
    type SidebarSortField,
    type SidebarTab,
  } from "../utils/sidebarDomain";

  let {
    sidebarMode,
    sidebarTab,
    tmdbConfigured,
    filtersOpen,
    hasActiveFilters,
    filteredCount,
    searchQuery,
    searchField,
    sortField,
    sortDir,
    onOpenFilters,
    onSearchQueryChange,
    onSearchFieldChange,
    onSetSort,
  }: {
    sidebarMode: SidebarMode;
    sidebarTab: SidebarTab;
    tmdbConfigured: boolean;
    filtersOpen: boolean;
    hasActiveFilters: boolean;
    filteredCount: number;
    searchQuery: string;
    searchField: SidebarSearchField;
    sortField: SidebarSortField;
    sortDir: SidebarSortDir;
    onOpenFilters: () => void;
    onSearchQueryChange: (value: string) => void;
    onSearchFieldChange: (field: SidebarSearchField) => void;
    onSetSort: (field: SidebarSortField, dir: SidebarSortDir) => void;
  } = $props();

  type Menu = "search" | "sort";

  const menuId = $props.id();
  const MENU_KEYS = ["ArrowDown", "ArrowUp", "Home", "End"];

  let openMenu = $state<Menu | null>(null);
  let searchButton = $state<HTMLButtonElement>();
  let searchInput: HTMLInputElement;
  let sortButton = $state<HTMLButtonElement>();

  let fieldGroups = $derived(searchFieldGroups(sidebarTab, tmdbConfigured));
  // TMDB results are not the library: its filters and sort do not apply to them.
  let searchingTmdb = $derived(sidebarMode === "items" && searchField === "tmdb");
  let isDefaultSort = $derived(sortField === "title" && sortDir === "asc");
  let placeholder = $derived.by(() => {
    const fieldPlaceholder = SIDEBAR_SEARCH_FIELDS[searchField].placeholder;
    if (fieldPlaceholder) return fieldPlaceholder;
    if (sidebarMode === "collections") {
      return `Search ${filteredCount} collection${filteredCount === 1 ? "" : "s"}...`;
    }
    return `Search ${filteredCount} ${sidebarTab === "movie" ? "movies" : "shows"}...`;
  });

  let loadedSection = $state<string | null>(null);
  $effect(() => {
    const section = `${sidebarTab}:${sidebarMode}`;
    if (loadedSection !== null && section !== loadedSection) {
      openMenu = null;
    }
    loadedSection = section;
  });

  function toggleMenu(event: MouseEvent, menu: Menu) {
    // The window click listener closes menus on any other click.
    event.stopPropagation();
    openMenu = openMenu === menu ? null : menu;
  }

  function closeMenu(button: HTMLButtonElement | undefined) {
    openMenu = null;
    button?.focus({ preventScroll: true });
  }

  /** Moves focus into a menu as it opens, onto its checked item. */
  function focusCheckedItem(menu: HTMLElement) {
    menu.querySelector<HTMLElement>('[aria-checked="true"]')?.focus({ preventScroll: true });
  }

  function onMenuButtonKeydown(event: KeyboardEvent, menu: Menu) {
    if (MENU_KEYS.includes(event.key)) {
      event.preventDefault();
      openMenu = menu;
    }
  }

  function onMenuKeydown(
    event: KeyboardEvent & { currentTarget: HTMLElement },
    button: HTMLButtonElement | undefined,
  ) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMenu(button);
    } else if (event.key === "Tab") {
      openMenu = null;
    } else if (MENU_KEYS.includes(event.key)) {
      event.preventDefault();
      const items = [
        ...event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitemradio"]'),
      ];
      const index = items.indexOf(document.activeElement as HTMLElement);
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[next]?.focus({ preventScroll: true });
    }
  }

  function chooseSearchField(field: SidebarSearchField) {
    onSearchFieldChange(field);
    openMenu = null;
    searchInput.focus({ preventScroll: true });
  }

  function chooseSort(field: SidebarSortField) {
    const nextDir =
      sortField === field ? (sortDir === "asc" ? "desc" : "asc") : defaultSortDir(field);
    onSetSort(field, nextDir);
    closeMenu(sortButton);
  }
</script>

<svelte:window onclick={() => (openMenu = null)} />

<div class="sidebar-controls">
  {#if !searchingTmdb}
    <button
      type="button"
      class="btn btn-ghost btn-icon filter-btn"
      class:has-filter={hasActiveFilters}
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
    {#if sidebarMode === "items"}
      <div class="search-field-picker">
        <button
          type="button"
          class="search-field-btn"
          class:active={searchField !== "title"}
          bind:this={searchButton}
          aria-label="Choose search field"
          aria-haspopup="menu"
          aria-controls="{menuId}-search"
          aria-expanded={openMenu === "search"}
          title="Search by field"
          onclick={(event) => toggleMenu(event, "search")}
          onkeydown={(event) => onMenuButtonKeydown(event, "search")}
        >
          <Search size={13} />
          <ChevronDown size={11} />
        </button>

        {#if openMenu === "search"}
          <div
            id="{menuId}-search"
            class="search-field-dropdown"
            role="menu"
            aria-label="Search by"
            tabindex="-1"
            onkeydown={(event) => onMenuKeydown(event, searchButton)}
            {@attach focusCheckedItem}
          >
            {#each fieldGroups as group, index (group.label)}
              {#if index > 0}
                <div class="search-field-separator" role="separator"></div>
              {/if}
              <div role="group" aria-label={group.label}>
                <!-- Headings only matter once there is more than one group. -->
                {#if fieldGroups.length > 1}
                  <div class="search-field-group" aria-hidden="true">{group.label}</div>
                {/if}
                {#each group.fields as field (field)}
                  <button
                    type="button"
                    class="search-field-option"
                    class:active={searchField === field}
                    role="menuitemradio"
                    aria-checked={searchField === field}
                    tabindex="-1"
                    onclick={() => chooseSearchField(field)}
                  >
                    {SIDEBAR_SEARCH_FIELDS[field].label}
                  </button>
                {/each}
              </div>
            {/each}
          </div>
        {/if}
      </div>
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
    {/if}
  </div>

  {#if sidebarMode !== "collections" && !searchingTmdb}
    <div class="sort-picker">
      <button
        type="button"
        class="sort-btn"
        bind:this={sortButton}
        class:active={!isDefaultSort}
        aria-label="Choose sort order"
        aria-haspopup="menu"
        aria-controls="{menuId}-sort"
        aria-expanded={openMenu === "sort"}
        title="Sort order"
        onclick={(event) => toggleMenu(event, "sort")}
        onkeydown={(event) => onMenuButtonKeydown(event, "sort")}
      >
        {#if isDefaultSort}
          <ArrowUpDown size={13} />
        {:else if sortDir === "asc"}
          <ArrowUpNarrowWide size={13} />
        {:else}
          <ArrowDownWideNarrow size={13} />
        {/if}
        {#if !isDefaultSort}
          <span class="sort-field-label">{SIDEBAR_SORT_OPTIONS[sortField].shortLabel}</span>
        {/if}
      </button>

      {#if openMenu === "sort"}
        <div
          id="{menuId}-sort"
          class="sort-dropdown"
          role="menu"
          aria-label="Sort by"
          tabindex="-1"
          onkeydown={(event) => onMenuKeydown(event, sortButton)}
          {@attach focusCheckedItem}
        >
          {#each SIDEBAR_SORT_FIELDS as field (field)}
            <button
              type="button"
              class="sort-option"
              class:active={sortField === field}
              role="menuitemradio"
              aria-checked={sortField === field}
              tabindex="-1"
              onclick={() => chooseSort(field)}
            >
              <span>{SIDEBAR_SORT_OPTIONS[field].label}</span>
              {#if sortField === field}
                <span class="sort-dir-arrow">{sortDir === "asc" ? "Asc" : "Desc"}</span>
              {/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>
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

  .sort-picker,
  .search-field-picker {
    position: relative;
    flex-shrink: 0;
  }

  .sort-btn,
  .search-field-btn {
    display: flex;
    align-items: center;
    gap: 3px;
    padding: var(--space-2);
    background: transparent;
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    color: var(--text-tertiary);
    cursor: pointer;
    font-size: var(--text-xs);
    white-space: nowrap;
  }

  .sort-btn:hover,
  .sort-btn.active {
    color: var(--accent);
    background: var(--accent-muted);
    border-color: var(--accent);
  }

  .sort-field-label {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--accent);
  }

  .sort-dropdown,
  .search-field-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    z-index: 200;
    background: var(--bg-secondary);
    border: var(--border-accent);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-md);
    min-width: 110px;
    overflow: hidden;
    white-space: nowrap;
  }

  .sort-dropdown {
    right: 0;
  }

  .search-field-dropdown {
    left: 0;
  }

  .sort-option,
  .search-field-option {
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: transparent;
    border: none;
    text-align: left;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    cursor: pointer;
  }

  .sort-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .search-field-option {
    display: block;
  }

  .search-field-group {
    padding: var(--space-2) var(--space-3) var(--space-1);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-tertiary);
  }

  .search-field-separator {
    margin: var(--space-1) 0;
    border-top: var(--border-subtle);
  }

  .sort-option:hover,
  .search-field-option:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  .sort-option.active,
  .search-field-option.active {
    color: var(--accent);
    font-weight: 500;
  }

  .sort-dir-arrow {
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
    background: var(--bg-tertiary);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
  }

  .search-field-btn {
    border: none;
    border-right: var(--border-subtle);
    border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  }

  .search-field-btn:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .search-field-btn.active {
    color: var(--accent);
    background: var(--accent-muted);
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
