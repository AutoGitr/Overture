<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionOptions,
    listItemsOptions,
    listCollectionGroupsOptions,
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
    enabled: collection !== null && routedCollectionView() === "configure",
  }));
  const groupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: collection !== null && routedCollectionView() === "configure",
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
  {#if routedCollectionView() === "configure"}
    <DataStatus
      label="collection groups"
      error={groupsQuery.error}
      loading={groupsQuery.isFetching}
      hasData={groupsQuery.data !== undefined}
      onretry={() => groupsQuery.refetch()}
    />
  {/if}
  {#key collectionId}<CollectionManager
      {collection}
      groups={groupsQuery.data ?? []}
      libraryItems={itemsQuery.data?.items ?? []}
    />{/key}
{:else}<p class="text-muted">Select a collection from the sidebar</p>{/if}
