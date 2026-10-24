<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCatalogEntryOptions,
    getPublicDatasetStatusOptions,
    getTmdbCollectionOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import DetailPanel from "../../components/DetailPanel.svelte";
  import CollectionMembers from "../../components/CollectionMembers.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { routedCatalogEntry, routedItemView } from "../routes";

  let target = $derived(routedCatalogEntry());
  const status = createQuery(() => getPublicDatasetStatusOptions());
  const query = createQuery(() => ({
    ...getCatalogEntryOptions({ path: target ?? { media_type: "movie", entry_key: "" } }),
    enabled: !!target && status.data?.enabled === true,
  }));
  let detail = $derived(query.data ?? null);
  let entry = $derived(detail?.draft ?? detail?.entry);
  const membersQuery = createQuery(() => ({
    ...getTmdbCollectionOptions({ path: { collection_id: entry?.tmdb_id ?? 0 } }),
    enabled:
      target?.media_type === "collection" &&
      !!entry?.tmdb_id &&
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
    label="catalog entry"
    error={query.error ?? status.error}
    loading={query.isFetching || status.isFetching}
    hasData={query.data !== undefined}
    onretry={() => {
      void status.refetch();
      void query.refetch();
    }}
  />
  <DetailPanel {detail} view={routedItemView()}>
    {#snippet members()}
      {#if target.media_type === "collection"}
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
      {/if}
    {/snippet}
  </DetailPanel>
{/if}
