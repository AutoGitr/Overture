<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { getCollectionOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CollectionThemePanel from "../../components/CollectionThemePanel.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { routedCollectionId } from "../routes";

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
{#key collectionId}<CollectionThemePanel {collection} />{/key}
