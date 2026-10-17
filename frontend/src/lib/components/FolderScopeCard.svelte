<script lang="ts">
  import { sidebarState } from "../stores/sidebarState.svelte";
  import type { FolderScope } from "../utils/folderScope.svelte";
  import DataStatus from "./DataStatus.svelte";
  import FolderChecklist from "./FolderChecklist.svelte";
  import SidebarItemsOption from "./SidebarItemsOption.svelte";

  let { scope }: { scope: FolderScope } = $props();
</script>

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
      <FolderChecklist
        folders={scope.folders}
        selectedMovieFolders={scope.useSidebarItems ? [] : scope.movieFolders}
        selectedShowFolders={scope.useSidebarItems ? [] : scope.showFolders}
        ontoggle={(folder, type) => scope.toggle(folder, type)}
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
