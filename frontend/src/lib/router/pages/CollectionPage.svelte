<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { listCollectionsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CollectionThemePanel from "../../components/CollectionThemePanel.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { collectionState } from "../../stores/collectionState.svelte";
  import { selectedState } from "../../stores/selectedState.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { parseIdFromSlug } from "../../utils/slug";
  import { route } from "../routes";

  // Shares its query key/cache with the same query in Sidebar.svelte, so this
  // never triggers a duplicate network request.
  const collectionsQuery = createQuery(() =>
    listCollectionsOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  let collections = $derived(collectionsQuery.data ?? []);

  // A collection and an item can never be selected at the same time.
  $effect(() => {
    if (selectedState.subject) selectedState.selectItem(null);
  });

  $effect(() => {
    const collectionSlug = route.params.collectionSlug;
    uiState.mobileShowDetail = !!collectionSlug;

    if (!collectionSlug) {
      if (collectionState.selectedCollection) collectionState.selectCollection(null);
      return;
    }
    const collectionId = parseIdFromSlug(collectionSlug);

    // Wait for the first load to land before deciding "not found" - avoids a
    // flash of the empty state while the list is still in flight.
    if (collectionsQuery.isPending || (!collectionsQuery.data && collectionsQuery.isError)) {
      collectionState.selectCollection(null);
      return;
    }

    const found = collections.find((candidate) => candidate.id === collectionId) ?? null;
    collectionState.selectCollection(found);
  });
</script>

<DataStatus
  label="collection"
  error={collectionsQuery.error}
  loading={collectionsQuery.isFetching}
  hasData={collectionsQuery.data !== undefined}
  onretry={() => collectionsQuery.refetch()}
/>
{#if collectionsQuery.data}
  {#key collectionState.selectedCollection?.id}
    <CollectionThemePanel />
  {/key}
{/if}
