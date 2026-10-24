<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import Settings from "@lucide/svelte/icons/settings";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getLibrariesOptions,
    listItemsOptions,
    listCollectionGroupsOptions,
    getTmdbCollectionOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { CollectionDraft } from "../../utils/collectionForms.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { route } from "../routes";
  import DetailPanelBase from "../../components/DetailPanelBase.svelte";
  import ConfigureNavigation from "../../components/ConfigureNavigation.svelte";
  import StatusTab from "../../components/StatusTab.svelte";
  import CollectionConfigure from "../../components/CollectionConfigure.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  const formId = $props.id();
  let seedId = $derived(Number(route.search.tmdb_id) || 0);
  const seed = createQuery(() => ({
    ...getTmdbCollectionOptions({ path: { collection_id: seedId } }),
    enabled: seedId > 0,
  }));
  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  const groups = createQuery(() =>
    listCollectionGroupsOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  const form = new CollectionDraft(
    uiState.sidebarTab,
    () => libraries.data ?? [],
    () => seed.data ?? null,
  );
  const items = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: !!form.libraryId,
  }));
</script>

<DetailPanelBase
  isEmpty={false}
  subjectKey="new-collection"
  title="New collection"
  emptyMessage="Create a collection"
  posterUrl={null}
  subtabRole="group"
  subtabLabel="Configure navigation"
>
  {#snippet emptyIcon()}<Layers size={64} />{/snippet}
  {#snippet posterIcon()}<Layers size={48} />{/snippet}
  {#snippet badges()}{/snippet}
  {#snippet tabs()}<StatusTab icon={Settings} label="Configure" active />{/snippet}
  {#snippet subtabs()}<ConfigureNavigation {formId} />{/snippet}
  {#snippet subtabActions()}<button
      class="tab-item"
      type="submit"
      form={formId}
      disabled={form.busy || !form.canSubmit}>Create collection</button
    >{/snippet}
  {#snippet content()}
    <DataStatus
      label="libraries"
      error={libraries.error}
      loading={libraries.isFetching}
      hasData={libraries.data !== undefined}
      onretry={() => libraries.refetch()}
    />
    <DataStatus
      label="collection groups"
      error={groups.error}
      loading={groups.isFetching}
      hasData={groups.data !== undefined}
      onretry={() => groups.refetch()}
    />
    <DataStatus
      label="library items"
      error={items.error}
      loading={items.isFetching}
      hasData={items.data !== undefined}
      onretry={() => items.refetch()}
    />
    {#if seedId}<DataStatus
        label="TMDB collection"
        error={seed.error}
        loading={seed.isFetching}
        hasData={seed.data !== undefined}
        onretry={() => seed.refetch()}
      />{/if}
    {#if form.request.error}<DataStatus
        label="collection creation"
        error={form.request.error}
        loading={false}
        hasData={false}
        onretry={() => form.save()}
      />{/if}
    <CollectionConfigure
      editor={form}
      libraryItems={items.data?.items ?? []}
      groups={groups.data ?? []}
      libraries={libraries.data ?? []}
      {formId}
    />
  {/snippet}
</DetailPanelBase>
