<script lang="ts">
  import { allValuesSelected } from "../utils/popupSelection";

  interface ChecklistLibrary {
    id: string;
    title: string;
    count?: number | null;
  }

  let {
    movieLibraries = [],
    showLibraries = [],
    selectedIds,
    loading = false,
    error = "",
    onretry,
    emptyMessage = "No libraries found on media server.",
    ontoggle,
    ontoggleall,
  }: {
    movieLibraries?: ChecklistLibrary[];
    showLibraries?: ChecklistLibrary[];
    selectedIds: string[];
    loading?: boolean;
    error?: string;
    onretry?: () => void;
    emptyMessage?: string;
    ontoggle: (id: string) => void;
    ontoggleall: (checked: boolean) => void;
  } = $props();

  let libraryIds = $derived([...movieLibraries, ...showLibraries].map((library) => library.id));
  let allSelected = $derived(allValuesSelected(selectedIds, libraryIds));
</script>

<div class="section-controls">
  <label class="checkbox-group">
    <input
      type="checkbox"
      checked={allSelected}
      disabled={loading || !!error || libraryIds.length === 0}
      onchange={(event) => ontoggleall((event.currentTarget as HTMLInputElement).checked)}
    />
    <span>{allSelected ? "Deselect All" : "Select All"}</span>
  </label>
</div>
<div class="section-list">
  {#if loading}
    <span class="muted-text">Loading libraries...</span>
  {:else if error}
    <p role="alert">{error}</p>
    {#if onretry}
      <button class="btn btn-ghost btn-sm" onclick={onretry}>Retry</button>
    {/if}
  {:else if libraryIds.length === 0}
    <span class="muted-text">{emptyMessage}</span>
  {:else}
    {#if movieLibraries.length}
      <div class="section-heading">Movies</div>
      {#each movieLibraries as library (library.id)}
        <label class="checkbox-group">
          <input
            type="checkbox"
            checked={selectedIds.includes(library.id)}
            onchange={() => ontoggle(library.id)}
          />
          <span>
            {library.title}
            {#if library.count != null}
              <span class="item-count">{library.count}</span>
            {/if}
          </span>
        </label>
      {/each}
    {/if}
    {#if showLibraries.length}
      <div class="section-heading spaced-heading">Shows</div>
      {#each showLibraries as library (library.id)}
        <label class="checkbox-group">
          <input
            type="checkbox"
            checked={selectedIds.includes(library.id)}
            onchange={() => ontoggle(library.id)}
          />
          <span>
            {library.title}
            {#if library.count != null}
              <span class="item-count">{library.count}</span>
            {/if}
          </span>
        </label>
      {/each}
    {/if}
  {/if}
</div>
