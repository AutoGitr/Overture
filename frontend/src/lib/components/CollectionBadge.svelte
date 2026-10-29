<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import { createQuery } from "@tanstack/svelte-query";
  import { getCatalogEntryOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { goToCatalogEntry, goToCollection } from "../router/routes";

  // One link at most, and its icon names where it goes: the sidebar's
  // collection icon for the library's collection, OvertureDB's for its entry.

  let {
    tmdbId,
    libraryCollectionId = null,
    datasetEnabled,
  }: {
    tmdbId: number;
    libraryCollectionId?: number | null;
    datasetEnabled: boolean;
  } = $props();
  const catalog = createQuery(() => ({
    ...getCatalogEntryOptions({ path: { media_type: "collection", entry_key: `tmdb-${tmdbId}` } }),
    enabled: datasetEnabled && libraryCollectionId === null,
    retry: false,
  }));
  let entry = $derived(datasetEnabled ? catalog.data : null);
</script>

{#if libraryCollectionId !== null}
  <button
    class="btn btn-ghost btn-sm"
    onclick={() => {
      if (libraryCollectionId !== null)
        goToCollection({ id: libraryCollectionId, title: "Collection", media_type: "movie" });
    }}><Layers size={16} />Collection</button
  >
{:else if entry}
  <button
    class="btn btn-ghost btn-sm"
    onclick={() => {
      if (entry) goToCatalogEntry({ media_type: "collection", entry_key: entry.entry_key });
    }}><img src="/brand/overturedb-tab.svg" width="16" height="16" alt="" />Collection: {entry.entry.title}</button
  >
{/if}
