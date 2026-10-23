<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCatalogEntryOptions,
    getPublicDatasetStatusOptions,
    getTmdbCollectionOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CatalogDetailPanel from "../../components/CatalogDetailPanel.svelte";
  import CollectionMembers from "../../components/CollectionMembers.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { routedCatalogEntry, routedItemView } from "../routes";

  let target = $derived(routedCatalogEntry());
  const status = createQuery(() => getPublicDatasetStatusOptions());
  const query = createQuery(() => ({
    ...getCatalogEntryOptions({ path: target ?? { media_type: "collection", entry_key: "" } }),
    enabled: !!target && status.data?.enabled === true,
  }));
  const membersQuery = createQuery(() => ({
    ...getTmdbCollectionOptions({ path: { collection_id: query.data?.entry.tmdb_id ?? 0 } }),
    enabled:
      status.data?.enabled === true &&
      !!query.data?.entry.tmdb_id &&
      settingsState.current.tmdb_configured,
  }));
  $effect(() => {
    uiState.mobileShowDetail = true;
  });
</script>

{#if status.data?.enabled === false}
  <p class="text-muted">Enable OvertureDB to browse the catalog.</p>
{:else if !target}
  <p role="alert">Invalid catalog entry.</p>
{:else}
  <DataStatus
    label="catalog collection"
    error={query.error ?? status.error}
    loading={query.isFetching || status.isFetching}
    hasData={query.data !== undefined}
    onretry={() => {
      void status.refetch();
      void query.refetch();
    }}
  />
  <CatalogDetailPanel detail={query.data ?? null} view={routedItemView()}>
    {#snippet members()}
      {#if settingsState.current.tmdb_configured}
        <DataStatus
          label="collection members"
          error={membersQuery.error}
          loading={membersQuery.isFetching}
          hasData={membersQuery.data !== undefined}
          onretry={() => membersQuery.refetch()}
        />
        {#if membersQuery.data}<CollectionMembers members={membersQuery.data.items} />{/if}
      {:else}<p class="text-muted">Configure TMDB to see this collection's members.</p>{/if}
    {/snippet}
  </CatalogDetailPanel>
{/if}
