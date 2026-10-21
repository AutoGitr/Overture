<script lang="ts">
  import { sidebarState } from "../stores/sidebarState.svelte";
  import type { FolderScope } from "../utils/folderScope.svelte";
  import Checklist, { type ChecklistGroup } from "./Checklist.svelte";
  import DataStatus from "./DataStatus.svelte";
  import SidebarItemsOption from "./SidebarItemsOption.svelte";

  let { scope }: { scope: FolderScope } = $props();

  let movieFolders = $derived(scope.useSidebarItems ? [] : scope.movieFolders);
  let showFolders = $derived(scope.useSidebarItems ? [] : scope.showFolders);
  let totalFolders = $derived(scope.folders.movies.length + scope.folders.shows.length);
  let groups = $derived<ChecklistGroup[]>([
    {
      key: "movie",
      label: "Movies",
      options: scope.folders.movies.map((folder) => ({
        id: folder,
        label: folder,
        checked: movieFolders.includes(folder),
      })),
    },
    {
      key: "show",
      label: "Shows",
      options: scope.folders.shows.map((folder) => ({
        id: folder,
        label: folder,
        checked: showFolders.includes(folder),
      })),
    },
  ]);
  let allSelected = $derived(
    totalFolders > 0 &&
      movieFolders.length === scope.folders.movies.length &&
      showFolders.length === scope.folders.shows.length,
  );
</script>

{#snippet noFolders()}
  <span class="muted-text">No media folders found.</span>
{/snippet}

<DataStatus
  label="folders"
  error={scope.query.error}
  loading={scope.query.isFetching}
  hasData={scope.query.data !== undefined}
  onretry={() => scope.query.refetch()}
/>
<div class="option-card">
  <span class="form-label">Folders</span>
  <div style:opacity={scope.useSidebarItems ? 0.5 : undefined}>
    {#if scope.query.data}
      <Checklist
        {groups}
        {allSelected}
        selectAllDisabled={totalFolders === 0}
        notice={totalFolders === 0 ? noFolders : undefined}
        ontoggle={(groupKey, folder) =>
          scope.toggle(folder, groupKey === "show" ? "show" : "movie")}
        ontoggleall={(checked) => scope.toggleAll(checked)}
      />
    {/if}
  </div>
  <SidebarItemsOption
    checked={scope.useSidebarItems}
    sidebarItems={sidebarState.current}
    muted={!scope.useSidebarItems && scope.movieFolders.length + scope.showFolders.length > 0}
    onchange={(checked) => (scope.useSidebarItems = checked)}
  />
</div>
