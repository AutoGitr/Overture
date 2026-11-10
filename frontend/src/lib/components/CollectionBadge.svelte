<script lang="ts">
  import { MEDIA_ICONS } from "../utils/mediaIcons";
  import { createQuery } from "@tanstack/svelte-query";
  import { getCatalogEntryOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { goToCatalogEntry, goToCollection } from "../router/routes";
  import IdBadge from "./IdBadge.svelte";

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
  <IdBadge
    title="Open its collection"
    onselect={() => goToCollection({ id: libraryCollectionId, title: "Collection" })}
  >
    <MEDIA_ICONS.collection size={30} aria-hidden="true" />
  </IdBadge>
{:else if entry}
  {@const entryKey = entry.entry_key}
  <IdBadge
    title={`Open its collection, ${entry.entry.title}, in OvertureDB`}
    icon="/brand/overturedb-tab.svg"
    alt="OvertureDB collection"
    onselect={() => goToCatalogEntry({ media_type: "collection", entry_key: entryKey })}
  />
{/if}
