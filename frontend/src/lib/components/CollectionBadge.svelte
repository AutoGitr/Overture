<script lang="ts">
  import { MEDIA_ICONS } from "../utils/mediaIcons";
  import { createQuery } from "@tanstack/svelte-query";
  import { getCatalogEntryOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { goToCatalogEntry, goToCollection } from "../router/routes";
  import IdBadge from "./IdBadge.svelte";

  // One link at most, always with the collection icon: the icon says what it
  // opens, the title where. The OvertureDB logo names only the subject itself.

  let {
    tmdbId,
    libraryCollectionId = null,
    catalogEnabled,
  }: {
    tmdbId: number;
    libraryCollectionId?: number | null;
    catalogEnabled: boolean;
  } = $props();
  const catalog = createQuery(() => ({
    ...getCatalogEntryOptions({ path: { media_type: "collection", entry_key: `tmdb-${tmdbId}` } }),
    enabled: catalogEnabled && libraryCollectionId === null,
    retry: false,
  }));
  let entry = $derived(catalogEnabled ? catalog.data : null);
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
    onselect={() => goToCatalogEntry({ media_type: "collection", entry_key: entryKey })}
  >
    <MEDIA_ICONS.collection size={30} aria-hidden="true" />
  </IdBadge>
{/if}
