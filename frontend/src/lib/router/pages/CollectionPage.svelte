<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionOptions,
    getLibrariesOptions,
    listItemsOptions,
    listCollectionGroupsOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import NewCollectionPage from "./NewCollectionPage.svelte";
  import CollectionManager from "../../components/CollectionManager.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { route, routedCollectionId, routedCollectionView } from "../routes";

  let creating = $derived(route.pathname.endsWith("/collections/new"));
  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
  );
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
    uiState.mobileShowDetail = creating || collectionId !== null;
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
{#if creating}
  {#key `${uiState.sidebarTab}:${route.search.draft ?? ""}`}<NewCollectionPage />{/key}
{:else if collection}
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
      libraries={libraries.data ?? []}
      groups={groupsQuery.data ?? []}
      libraryItems={itemsQuery.data?.items ?? []}
    />{/key}
{:else}<p class="text-muted">Select a collection from the sidebar</p>{/if}
