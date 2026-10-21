<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { listCollectionsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CollectionThemePanel from "../../components/CollectionThemePanel.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { routedCollectionId } from "../routes";

  // Shares its query key/cache with the same query in Sidebar.svelte, so this
  // never triggers a duplicate network request.
  const collectionsQuery = createQuery(() =>
    listCollectionsOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  let collectionId = $derived(routedCollectionId());
  let collection = $derived(
    collectionsQuery.data?.find((candidate) => candidate.id === collectionId) ?? null,
  );

  $effect(() => {
    uiState.mobileShowDetail = collectionId !== null;
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
  {#key collection?.id}
    <CollectionThemePanel {collection} />
  {/key}
{/if}
