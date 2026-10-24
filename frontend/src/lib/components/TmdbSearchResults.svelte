<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import {
    getTmdbCollectionOptions,
    searchTmdbOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    MediaItemRead,
    CollectionRead,
    TmdbCollectionResult,
    TmdbItemResult,
  } from "../../generated/rest/types.gen";
  import {
    goToItem,
    goToItemArt,
    goToItemThemes,
    goToNewCollection,
    goToCollectionView,
    routedItem,
    searchParams,
  } from "../router/routes";
  import { settingsState } from "../stores/settingsState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { statusTone } from "../utils/sidebarDomain";
  import { sidebarState, type AdvanceEntry } from "../stores/sidebarState.svelte";
  import { debounced } from "../utils/delayedFlag.svelte";
  import type { SidebarTab } from "../utils/sidebarDomain";
  import DataStatus from "./DataStatus.svelte";
  import SidebarRow from "./SidebarRow.svelte";
  import SidebarGroupBrowser from "./SidebarGroupBrowser.svelte";
  import { remotePosterUrl } from "../utils/artDisplay";

  let {
    query,
    tab,
    libraryItems,
    libraryRow,
    collections = [],
    collectionsOnly = false,
    onOpen,
  }: {
    query: string;
    tab: SidebarTab;
    /** The tab's stored items; a result that is one of them shows as it. */
    libraryItems: MediaItemRead[];
    libraryRow: Snippet<[MediaItemRead, number, string]>;
    collections?: CollectionRead[];
    collectionsOnly?: boolean;
    onOpen: (navigate: () => void) => void;
  } = $props();

  type Result = TmdbItemResult | TmdbCollectionResult;

  const search = debounced(() => query.trim());
  const resultsQuery = createQuery(() => ({
    ...searchTmdbOptions({ query: { media_type: tab, query: search.current } }),
    enabled: search.current.length > 0,
  }));
  let groups = $derived(
    resultsQuery.data?.results.filter(
      (row): row is TmdbCollectionResult => row.kind === "collection",
    ) ?? [],
  );
  let collection = $derived(
    searchParams.get("tmdb_query") === search.current
      ? (groups.find((group) => group.tmdb_id === Number(searchParams.get("tmdb_collection"))) ??
          null)
      : null,
  );
  const collectionQuery = createQuery(() => ({
    ...getTmdbCollectionOptions({ path: { collection_id: collection?.tmdb_id ?? 0 } }),
    enabled: collection !== null,
  }));
  let activeQuery = $derived(collection ? collectionQuery : resultsQuery);
  let rows = $derived<TmdbItemResult[]>(
    collection
      ? (collectionQuery.data?.items ?? [])
      : collectionsOnly
        ? []
        : (resultsQuery.data?.results.filter((row): row is TmdbItemResult => row.kind === "item") ??
          []),
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
      searchParams.set("tmdb_query", search.current, { replace: true });
      searchParams.set("tmdb_collection", result.tmdb_id);
      return;
    }
    const { existing_item_id: id, title, media_type } = result;
    onOpen(() => void goToItem(id === null ? result : { id, title, media_type }));
  }
  function openAssets(result: Result, mode: "art" | "themes") {
    if (result.kind === "item") {
      const item =
        storedItem(result) ??
        (result.existing_item_id === null
          ? result
          : { id: result.existing_item_id, title: result.title, media_type: result.media_type });
      onOpen(() => (mode === "art" ? goToItemArt(item) : goToItemThemes(item)));
      return;
    }
    const existing = collections.find((entry) => entry.tmdb_collection_id === result.tmdb_id);
    onOpen(() =>
      existing ? goToCollectionView(existing, mode) : goToNewCollection("movie", result.tmdb_id),
    );
  }

  function back() {
    searchParams.delete("tmdb_collection");
    searchParams.delete("tmdb_query", undefined, { replace: true });
  }
</script>

<div class="tmdb-results">
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
    <SidebarGroupBrowser
      groups={search.current ? groups : []}
      {rows}
      selected={collection}
      groupTitle={(group) => group.title}
      groupKey={(group) => String(group.tmdb_id)}
      groupPoster={remotePosterUrl}
      groupEntry={collectionRow}
      entry={itemRow}
      getKey={(item) => item.tmdb_id}
      posterUrl={remotePosterUrl}
      onback={back}
      loading={!!search.current && activeQuery.isPending}
      message={!search.current
        ? "Search TMDB by title or ID"
        : activeQuery.isSuccess && !rows.length && (collection || !groups.length)
          ? "No TMDB results"
          : ""}
    />
  </div>
</div>

{#snippet collectionRow(result: TmdbCollectionResult, index: number, style: string)}
  {@render resultRow(result, index, style)}
{/snippet}
{#snippet itemRow(result: TmdbItemResult, index: number, style: string)}
  {@const stored = storedItem(result)}
  {#if stored}{@render libraryRow(stored, index, style)}{:else}{@render resultRow(
      result,
      index,
      style,
    )}{/if}
{/snippet}
{#snippet resultRow(result: Result, index: number, style: string)}
  {@const storedCollection =
    result.kind === "collection"
      ? collections.find((entry) => entry.tmdb_collection_id === result.tmdb_id)
      : undefined}
  <SidebarRow
    {style}
    {index}
    active={isActive(result)}
    tmdbResult={result}
    hideTheme={result.kind === "collection" && settingsState.current.media_server === "emby"}
    artStatus={statusTone(storedCollection?.art_status ?? "missing", false)}
    themeStatus={statusTone(
      storedCollection?.theme_status ?? "missing",
      !!storedCollection && downloadState.isDownloadingCollection(storedCollection.id),
    )}
    onSelect={() => select(result)}
    onOpenArt={() => openAssets(result, "art")}
    onOpenThemes={() => openAssets(result, "themes")}
  />
{/snippet}

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
</style>
