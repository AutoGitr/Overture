<script lang="ts">
  import type { FolderRootsResponse } from "../../generated/rest/types.gen";

  let {
    folders,
    selectedMovieFolders,
    selectedShowFolders,
    ontoggle,
    ontoggleall,
  }: {
    folders: FolderRootsResponse;
    selectedMovieFolders: string[];
    selectedShowFolders: string[];
    ontoggle: (folder: string, type: "movie" | "show") => void;
    ontoggleall: (checked: boolean) => void;
  } = $props();

  let totalFolders = $derived(folders.movies.length + folders.shows.length);
  let allSelected = $derived(
    totalFolders > 0 &&
      selectedMovieFolders.length === folders.movies.length &&
      selectedShowFolders.length === folders.shows.length,
  );
</script>

<div class="section-controls">
  <label class="checkbox-group">
    <input
      type="checkbox"
      checked={allSelected}
      disabled={totalFolders === 0}
      onchange={(event) => ontoggleall((event.currentTarget as HTMLInputElement).checked)}
    />
    <span>{allSelected ? "Deselect All" : "Select All"}</span>
  </label>
</div>
<div class="section-list">
  {#if totalFolders === 0}
    <span class="muted-text">No media folders found.</span>
  {:else}
    {#if folders.movies.length}
      <div class="section-heading">Movies</div>
      {#each folders.movies as folder (folder)}
        <label class="checkbox-group">
          <input
            type="checkbox"
            checked={selectedMovieFolders.includes(folder)}
            onchange={() => ontoggle(folder, "movie")}
          />
          <span>{folder}</span>
        </label>
      {/each}
    {/if}
    {#if folders.shows.length}
      <div class="section-heading spaced-heading">Shows</div>
      {#each folders.shows as folder (folder)}
        <label class="checkbox-group">
          <input
            type="checkbox"
            checked={selectedShowFolders.includes(folder)}
            onchange={() => ontoggle(folder, "show")}
          />
          <span>{folder}</span>
        </label>
      {/each}
    {/if}
  {/if}
</div>
