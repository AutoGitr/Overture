<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionOptions,
    listItemsOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CollectionManager from "../../components/CollectionManager.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { routedCollectionId, routedCollectionView } from "../routes";

  let collectionId = $derived(routedCollectionId());
  const collectionQuery = createQuery(() => ({
    ...getCollectionOptions({
      path: { collection_id: collectionId ?? 0 },
      query: { media_type: uiState.sidebarTab },
    }),
    enabled: collectionId !== null,
  }));
  let collection = $derived(
    collectionQuery.data?.id === collectionId ? collectionQuery.data : null,
  );
  const itemsQuery = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: collectionId !== null && routedCollectionView() === "members",
  }));
  $effect(() => {
    uiState.mobileShowDetail = collectionId !== null;
  });
</script>

{#if collectionId}
  <DataStatus
    label="collection"
    error={collectionQuery.error}
    loading={collectionQuery.isFetching}
    hasData={collectionQuery.data !== undefined}
    onretry={() => collectionQuery.refetch()}
  />
{/if}
{#if collection}
  {#key collectionId}<CollectionManager
      {collection}
      libraryItems={itemsQuery.data?.items ?? []}
    />{/key}
{:else}<p class="text-muted">Select a collection from the sidebar</p>{/if}
