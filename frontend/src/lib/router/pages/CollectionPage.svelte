<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionOptions,
    listItemsOptions,
    listCollectionGroupsOptions,
    getTmdbCollectionOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CollectionManager from "../../components/CollectionManager.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import DetailPanel from "../../components/DetailPanel.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { allLibraries } from "../../utils/libraries.svelte";
  import { route, routedCollectionId, routedCollectionView } from "../routes";

  let creating = $derived(route.pathname.endsWith("/collections/new"));
  const libraries = allLibraries();
  let collectionId = $derived(routedCollectionId());
  const collectionQuery = createQuery(() => ({
    ...getCollectionOptions({ path: { collection_id: collectionId ?? 0 } }),
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
  let needsItems = $derived(
    creating || (collection !== null && routedCollectionView() === "configure"),
  );
  const movieItems = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: "movie" } }),
    enabled: needsItems,
  }));
  const showItems = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: "show" } }),
    enabled: needsItems,
  }));
  let libraryItems = $derived([...(movieItems.data?.items ?? []), ...(showItems.data?.items ?? [])]);
  const groupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions(),
    enabled:
      creating ||
      (collection !== null && (!collection.managed || routedCollectionView() === "configure")),
  }));
  let groups = $derived(groupsQuery.data ?? []);
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
    {#each [movieItems, showItems] as items, index (index)}
      <DataStatus
        label="library items"
        error={items.error}
        loading={items.isFetching}
        hasData={items.data !== undefined}
        onretry={() => items.refetch()}
      />
    {/each}
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
  {#key creating
    ? `${route.search.draft ?? ""}`
    : `${collectionId}:${collection?.managed}`}<CollectionManager
      {collection}
      seed={creating ? (seed.data ?? null) : null}
      libraries={libraries.data ?? []}
      {groups}
      {libraryItems}
    />{/key}
{:else}<DetailPanel />{/if}
