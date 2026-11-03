<script lang="ts">
  import { allValuesSelected, type CollectionChoice } from "../utils/popupSelection";
  import Checklist, { type ChecklistGroup } from "./Checklist.svelte";

  interface ChecklistLibrary {
    id: string;
    title: string;
    count?: number | null;
  }

  /** The checklist entry for every collection, apart from the group names. */
  const ALL_COLLECTIONS = "\u0000all";

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
    collectionGroups,
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
    /** The groups a run can choose; left out where a run cannot include collections. */
    collectionGroups?: string[];
    /** What is chosen: every collection, or some of the groups. */
    collections?: CollectionChoice;
    /** Every collection (`null`) or one group was toggled. */
    oncollectiontoggle?: (group: string | null) => void;
    /** Select All also covers collections: choose them all, or none. */
    oncollectionsall?: (checked: boolean) => void;
  } = $props();

  let selectedSet = $derived<ReadonlySet<string>>(new Set(selectedIds));
  let libraryIds = $derived([...movieLibraries, ...showLibraries].map((library) => library.id));
  let allSelected = $derived(
    allValuesSelected(selectedIds, libraryIds) &&
      (collectionGroups === undefined ||
        !!collections?.all ||
        !!collections?.groups.length),
  );
  let groups = $derived<ChecklistGroup[]>(
    [
      { key: "movie", label: "Movies", libraries: movieLibraries },
      { key: "show", label: "Shows", libraries: showLibraries },
    ]
      .map(({ key, label, libraries }): ChecklistGroup => ({
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
        collectionGroups === undefined
          ? []
          : [
              {
                key: "collections",
                label: "Collections",
                options: [
                  {
                    id: ALL_COLLECTIONS,
                    label: "All collections",
                    checked: !!collections?.all,
                  },
                  ...collectionGroups.map((group) => ({
                    id: group,
                    label: group,
                    checked: !!collections?.groups.includes(group),
                  })),
                ],
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
  ontoggle={(group, id) =>
    group === "collections"
      ? oncollectiontoggle?.(id === ALL_COLLECTIONS ? null : id)
      : ontoggle(id)}
  ontoggleall={(checked) => {
    ontoggleall(checked);
    if (collectionGroups !== undefined) oncollectionsall?.(checked);
  }}
/>
