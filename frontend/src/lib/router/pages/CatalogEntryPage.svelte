<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCatalogEntryOptions,
    getPublicDatasetStatusOptions,
    getTmdbCollectionOptions,
    getTmdbItemOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { CatalogDraft, type CatalogContext } from "../../utils/catalogDraft";
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
  let entryTarget = $derived(
    detail ? { media_type: detail.entry.media_type, entry_key: detail.entry_key } : null,
  );
  const draft = new CatalogDraft(() => entryTarget);
  let entry = $derived(detail?.draft ?? detail?.entry);
  let view = $derived(routedItemView());
  const seasonsQuery = createQuery(() => ({
    ...getTmdbItemOptions({ path: { media_type: "show", tmdb_id: entry?.tmdb_id ?? 0 } }),
    enabled:
      entry?.media_type === "show" &&
      !!entry.tmdb_id &&
      settingsState.current.tmdb_configured &&
      view.artSubTab === "seasons",
  }));
  let catalog = $derived.by((): CatalogContext | null => {
    if (!detail || !entry || !entryTarget) return null;
    const seasons = [
      ...new Set(
        [
          ...(seasonsQuery.data?.seasons ?? []),
          ...(detail.entry.seasons ?? []),
          ...(entry.seasons ?? []),
        ].map((season) => season.season_num),
      ),
    ]
      .sort((a, b) => a - b)
      .map((season_num) => ({
        season_num,
        title:
          seasonsQuery.data?.seasons.find((season) => season.season_num === season_num)?.title ??
          null,
        poster_url:
          entry.seasons?.find((season) => season.season_num === season_num)?.poster_url ?? null,
        poster_preview_url: null,
      }));
    return { detail, entry, target: entryTarget, draft, seasons };
  });
  const membersQuery = createQuery(() => ({
    ...getTmdbCollectionOptions({
      path: { collection_id: entry?.tmdb_id ?? 0 },
      query: { artwork_source: "overturedb" },
    }),
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
  {#if entry?.media_type === "show" && view.artSubTab === "seasons"}
    <DataStatus
      label="TMDB seasons"
      error={seasonsQuery.error}
      loading={seasonsQuery.isFetching}
      hasData={seasonsQuery.data !== undefined}
      onretry={() => seasonsQuery.refetch()}
    />
  {/if}
  <DetailPanel {catalog} {view}>
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
          {#if membersQuery.data}<CollectionMembers
              members={membersQuery.data.items}
              catalog
            />{/if}
        {:else}<p class="text-muted">Configure TMDB to see this collection's members.</p>{/if}
      {/if}
    {/snippet}
  </DetailPanel>
{/if}
