<script lang="ts">
  import { allValuesSelected } from "../utils/popupSelection";
  import Checklist, { type ChecklistGroup } from "./Checklist.svelte";

  interface ChecklistLibrary {
    id: string;
    title: string;
    count?: number | null;
  }

  /** A collections choice listed after the libraries, such as one group. */
  interface CollectionChoice {
    id: string;
    label: string;
    checked: boolean;
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
    collections,
    oncollectiontoggle,
    oncollectionsall,
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
    /** Collection choices; left out where a run cannot include collections. */
    collections?: CollectionChoice[];
    oncollectiontoggle?: (id: string) => void;
    /** Select All also covers collections: choose them all, or none. */
    oncollectionsall?: (checked: boolean) => void;
  } = $props();

  let selectedSet = $derived<ReadonlySet<string>>(new Set(selectedIds));
  let libraryIds = $derived([...movieLibraries, ...showLibraries].map((library) => library.id));
  let allSelected = $derived(
    allValuesSelected(selectedIds, libraryIds) &&
      (collections === undefined || collections.some((choice) => choice.checked)),
  );
  let groups = $derived<ChecklistGroup[]>(
    [
      { key: "movie", label: "Movies", libraries: movieLibraries },
      { key: "show", label: "Shows", libraries: showLibraries },
    ]
      .map(({ key, label, libraries }) => ({
        key,
        label,
        options: libraries.map((library) => ({
          id: library.id,
          label: library.title,
          count: library.count,
          checked: selectedSet.has(library.id),
        })),
      }))
      .concat(
        collections === undefined
          ? []
          : [
              {
                key: "collections",
                label: "Collections",
                options: collections.map((choice) => ({ ...choice, count: undefined })),
              },
            ],
      ),
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
  ontoggle={(group, id) => (group === "collections" ? oncollectiontoggle?.(id) : ontoggle(id))}
  ontoggleall={(checked) => {
    ontoggleall(checked);
    oncollectionsall?.(checked);
  }}
/>
