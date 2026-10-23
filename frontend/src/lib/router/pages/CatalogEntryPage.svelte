<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCatalogEntryOptions,
    getPublicDatasetStatusOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import CatalogDetailPanel from "../../components/CatalogDetailPanel.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { routedCatalogEntry, routedItemView } from "../routes";

  let target = $derived(routedCatalogEntry());
  const status = createQuery(() => getPublicDatasetStatusOptions());
  const query = createQuery(() => ({
    ...getCatalogEntryOptions({ path: target ?? { media_type: "movie", entry_key: "" } }),
    enabled: !!target && status.data?.enabled === true,
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
  <CatalogDetailPanel detail={query.data ?? null} view={routedItemView()} />
{/if}
