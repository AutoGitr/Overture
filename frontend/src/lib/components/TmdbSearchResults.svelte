<script lang="ts">
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import {
    getTmdbCollectionOptions,
    searchTmdbOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    MediaItemRead,
    TmdbCollectionResult,
    TmdbItemResult,
  } from "../../generated/rest/types.gen";
  import { goToItem, routedItem } from "../router/routes";
  import { sidebarState, type AdvanceEntry } from "../stores/sidebarState.svelte";
  import { debounced } from "../utils/delayedFlag.svelte";
  import type { SidebarTab } from "../utils/sidebarDomain";
  import DataStatus from "./DataStatus.svelte";
  import SidebarRow from "./SidebarRow.svelte";
  import VirtualList from "./VirtualList.svelte";

  let {
    query,
    tab,
    libraryItems,
    libraryRow,
    onOpen,
  }: {
    query: string;
    tab: SidebarTab;
    /** The tab's stored items; a result that is one of them shows as it. */
    libraryItems: MediaItemRead[];
    libraryRow: Snippet<[MediaItemRead, number, string]>;
    onOpen: (navigate: () => void) => void;
  } = $props();

  type Result = TmdbItemResult | TmdbCollectionResult;

  const search = debounced(() => query.trim());
  // The collection expanded in the list, kept only for the search it came from.
  let expanded = $state<{ search: string; collection: TmdbCollectionResult } | null>(null);
  let collection = $derived(expanded?.search === search.current ? expanded.collection : null);

  const resultsQuery = createQuery(() => ({
    ...searchTmdbOptions({ query: { media_type: tab, query: search.current } }),
    enabled: search.current.length > 0,
  }));
  const collectionQuery = createQuery(() => ({
    ...getTmdbCollectionOptions({ path: { collection_id: collection?.tmdb_id ?? 0 } }),
    enabled: collection !== null,
  }));
  let activeQuery = $derived(collection ? collectionQuery : resultsQuery);
  let rows = $derived<Result[]>(
    collection ? (collectionQuery.data?.items ?? []) : (resultsQuery.data?.results ?? []),
  );
  // The library list is kept current (selections, sync, live events), while
  // a search result keeps the stored state from when it ran. Matching by TMDB
  // ID shows a title stored since then as its library row, badges included.
  let libraryByTmdbId = $derived(
    new Map(
      libraryItems.flatMap((item) =>
        item.tmdb_id === null ? [] : [[item.tmdb_id, item] as const],
      ),
    ),
  );

  function storedItem(result: Result): MediaItemRead | undefined {
    return result.kind === "item" ? libraryByTmdbId.get(result.tmdb_id) : undefined;
  }

  // Auto-advance moves through the titles shown, as it does through library rows.
  $effect(() => {
    sidebarState.tmdbResults = rows.flatMap((result): AdvanceEntry[] => {
      if (result.kind !== "item") return [];
      const id = storedItem(result)?.id ?? result.existing_item_id;
      if (id !== null) return [{ kind: "item", id }];
      const { tmdb_id, title, media_type } = result;
      return [{ kind: "tmdb", tmdb_id, title, media_type }];
    });
    return () => {
      sidebarState.tmdbResults = null;
    };
  });

  function isActive(result: Result): boolean {
    if (result.kind !== "item") return false;
    const open = routedItem();
    if (result.existing_item_id !== null) {
      return open?.kind === "item" && open.id === result.existing_item_id;
    }
    return open?.kind === "tmdb" && open.tmdbId === result.tmdb_id && tab === result.media_type;
  }

  function select(result: Result) {
    if (result.kind === "collection") {
      expanded = { search: search.current, collection: result };
      return;
    }
    const { existing_item_id: id, title, media_type } = result;
    onOpen(() => void goToItem(id === null ? result : { id, title, media_type }));
  }
</script>

<div class="tmdb-results">
  {#if collection}
    <button type="button" class="collection-back" onclick={() => (expanded = null)}>
      <ArrowLeft size={14} />
      <span>Back to results</span>
    </button>
    <div class="collection-heading truncate">{collection.title}</div>
  {/if}

  {#if search.current}
    <DataStatus
      label={collection ? "TMDB collection" : "TMDB results"}
      error={activeQuery.error}
      hasData={activeQuery.data !== undefined}
      loading={activeQuery.isFetching}
      onretry={() => activeQuery.refetch()}
    />
  {/if}

  <div class="tmdb-list">
    {#if !search.current}
      <div class="tmdb-empty">Search TMDB by title or ID</div>
    {:else if activeQuery.isPending}
      <div class="tmdb-empty">
        <LoaderCircle size={24} class="animate-spin" />
      </div>
    {:else if activeQuery.isSuccess && rows.length === 0}
      <div class="tmdb-empty">No TMDB results</div>
    {:else}
      <VirtualList
        width="100%"
        itemCount={rows.length}
        itemSize={88}
        getKey={(index) => `${rows[index]?.kind}-${rows[index]?.tmdb_id ?? index}`}
      >
        {#snippet row(index: number, style: string)}
          {@const result = rows[index]}
          {#if result}
            {@const stored = storedItem(result)}
            {#if stored}
              {@render libraryRow(stored, index, style)}
            {:else}
              <SidebarRow
                {style}
                {index}
                active={isActive(result)}
                tmdbResult={result}
                onSelect={() => select(result)}
              />
            {/if}
          {/if}
        {/snippet}
      </VirtualList>
    {/if}
  </div>
</div>

<style>
  .tmdb-results {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .tmdb-list {
    flex: 1;
    min-height: 0;
  }

  .collection-back {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    color: var(--accent);
    font-size: var(--text-sm);
    text-align: left;
  }

  .collection-back:hover {
    background: var(--bg-hover);
  }

  .collection-heading {
    padding: 0 var(--space-3) var(--space-2);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: 500;
    border-bottom: var(--border-subtle);
  }

  .tmdb-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-10);
    color: var(--text-tertiary);
    font-size: var(--text-sm);
  }
</style>
