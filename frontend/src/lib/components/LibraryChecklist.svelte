<script lang="ts">
  import { allValuesSelected } from "../utils/popupSelection";
  import Checklist, { type ChecklistGroup } from "./Checklist.svelte";

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

  let selectedSet = $derived<ReadonlySet<string>>(new Set(selectedIds));
  let libraryIds = $derived([...movieLibraries, ...showLibraries].map((library) => library.id));
  let allSelected = $derived(allValuesSelected(selectedIds, libraryIds));
  let groups = $derived<ChecklistGroup[]>(
    [
      { key: "movie", label: "Movies", libraries: movieLibraries },
      { key: "show", label: "Shows", libraries: showLibraries },
    ].map(({ key, label, libraries }) => ({
      key,
      label,
      options: libraries.map((library) => ({
        id: library.id,
        label: library.title,
        count: library.count,
        checked: selectedSet.has(library.id),
      })),
    })),
  );
</script>

{#snippet status()}
  {#if loading}
    <span class="hint">Loading libraries...</span>
  {:else if error}
    <p role="alert">{error}</p>
    {#if onretry}
      <button class="btn btn-ghost btn-sm" onclick={onretry}>Retry</button>
    {/if}
  {:else}
    <span class="hint">{emptyMessage}</span>
  {/if}
{/snippet}

<Checklist
  label="Libraries"
  {groups}
  {allSelected}
  selectAllDisabled={loading || !!error || libraryIds.length === 0}
  notice={loading || error || libraryIds.length === 0 ? status : undefined}
  ontoggle={(_group, id) => ontoggle(id)}
  {ontoggleall}
/>
