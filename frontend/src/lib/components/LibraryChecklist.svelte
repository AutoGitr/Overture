<script lang="ts">
  import { allValuesSelected } from "../utils/popupSelection";
  import LibraryOptions from "./LibraryOptions.svelte";

  let {
    libraries = [],
    selectedIds,
    loading = false,
    error = "",
    onretry,
    emptyMessage = "No libraries found on media server.",
    ontoggle,
    ontoggleall,
  }: {
    libraries?: readonly { id: string; title: string; server_id: number; count?: number | null }[];
    selectedIds: string[];
    loading?: boolean;
    error?: string;
    onretry?: () => void;
    emptyMessage?: string;
    ontoggle: (id: string) => void;
    ontoggleall: (checked: boolean) => void;
  } = $props();

  let libraryIds = $derived(libraries.map((library) => library.id));
  let allSelected = $derived(allValuesSelected(selectedIds, libraryIds));
  let unavailable = $derived(loading || !!error || libraryIds.length === 0);
</script>

<div class="checklist">
  <div class="heading-row">
    <span class="form-label">Libraries</span>
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={allSelected}
        disabled={unavailable}
        aria-label="{allSelected ? 'Deselect' : 'Select'} all libraries"
        onchange={(event) => ontoggleall(event.currentTarget.checked)}
      />
      <span aria-hidden="true">{allSelected ? "Deselect all" : "Select all"}</span>
    </label>
  </div>
  {#if loading}
    <span class="hint">Loading libraries...</span>
  {:else if error}
    <p role="alert">{error}</p>
    {#if onretry}
      <button class="btn btn-ghost btn-sm" onclick={onretry}>Retry</button>
    {/if}
  {:else if libraryIds.length === 0}
    <span class="hint">{emptyMessage}</span>
  {:else}
    <LibraryOptions {libraries} selected={selectedIds} {ontoggle} />
  {/if}
</div>

<style>
  .checklist {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
