<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionOptions,
    getLibrariesOptions,
    listItemsOptions,
    listCollectionGroupsOptions,
    getTmdbCollectionOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
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
  let seedId = $derived(creating ? Number(route.search.tmdb_id) || 0 : 0);
  const seed = createQuery(() => ({
    ...getTmdbCollectionOptions({ path: { collection_id: seedId } }),
    enabled: seedId > 0,
  }));
  const itemsQuery = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: creating || (collection !== null && routedCollectionView() === "configure"),
  }));
  const groupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: creating || (collection !== null && routedCollectionView() === "configure"),
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
{#if creating || collection}
  {#if creating || routedCollectionView() === "configure"}
    <DataStatus
      label="libraries"
      error={libraries.error}
      loading={libraries.isFetching}
      hasData={libraries.data !== undefined}
      onretry={() => libraries.refetch()}
    />
    <DataStatus
      label="library items"
      error={itemsQuery.error}
      loading={itemsQuery.isFetching}
      hasData={itemsQuery.data !== undefined}
      onretry={() => itemsQuery.refetch()}
    />
    {#if seedId}<DataStatus
        label="TMDB collection"
        error={seed.error}
        loading={seed.isFetching}
        hasData={seed.data !== undefined}
        onretry={() => seed.refetch()}
      />{/if}
    <DataStatus
      label="collection groups"
      error={groupsQuery.error}
      loading={groupsQuery.isFetching}
      hasData={groupsQuery.data !== undefined}
      onretry={() => groupsQuery.refetch()}
    />
  {/if}
  {#key creating ? `${uiState.sidebarTab}:${route.search.draft ?? ""}` : collectionId}<CollectionManager
      {collection}
      seed={creating ? (seed.data ?? null) : null}
      libraries={libraries.data ?? []}
      groups={groupsQuery.data ?? []}
      libraryItems={itemsQuery.data?.items ?? []}
    />{/key}
{:else}<p class="text-muted">Select a collection from the sidebar</p>{/if}
