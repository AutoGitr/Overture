<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import {
    getItemOptions,
    getTmdbItemOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import DataStatus from "../../components/DataStatus.svelte";
  import DetailPanel from "../../components/DetailPanel.svelte";
  import { findCachedLibraryItem } from "../../rest/cache";
  import { isApiError } from "../../rest/transport";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { cancelPendingAutoAdvance, preloadNextItem } from "../../utils/autoAdvance";
  import { goToItemView, goToLibrary, route, routedItem, routedItemView } from "../routes";

  let slug = $derived(routedItem());
  let itemId = $derived(slug?.kind === "item" ? slug.id : 0);
  let tmdbId = $derived(slug?.kind === "tmdb" ? slug.tmdbId : 0);
  let view = $derived(routedItemView());

  // `initialData` lets us reuse the item the user just clicked on from the
  // already-loaded library list (a different query key) so the detail view
  // appears instantly instead of waiting on a redundant network round-trip.
  // TanStack Query still treats this as "just fetched" data, so it remains
  // subject to the entity query's normal staleTime-driven background refresh.
  const itemQuery = createQuery(() => ({
    ...getItemOptions({ path: { item_id: itemId } }),
    enabled: itemId > 0,
    initialData: () => findCachedLibraryItem(itemId),
  }));
  // A TMDB title opens unsaved until its first selection stores it.
  const previewQuery = createQuery(() => ({
    ...getTmdbItemOptions({ path: { media_type: uiState.sidebarTab, tmdb_id: tmdbId } }),
    enabled: tmdbId > 0,
  }));
  let activeQuery = $derived(tmdbId ? previewQuery : itemQuery);

  // A query briefly keeps the previous route's data while its key changes, so
  // only data for the routed ID is shown.
  let item = $derived(itemQuery.data?.id === itemId ? itemQuery.data : null);
  // A stale cached title may since have been stored, so it waits for the
  // re-check rather than opening as new; a fresh one opens at once.
  let checkedPreview = $derived(
    previewQuery.data?.tmdb_id === tmdbId &&
      previewQuery.data.media_type === uiState.sidebarTab &&
      (previewQuery.isFetchedAfterMount || !previewQuery.isStale)
      ? previewQuery.data
      : null,
  );
  let preview = $derived(checkedPreview?.existing_item_id === null ? checkedPreview : null);

  onMount(() => {
    uiState.mobileShowDetail = true;
  });

  // Auto-advance opens the next item from here: its images load meanwhile.
  $effect(() => {
    if (item) preloadNextItem(item, settingsState.current);
  });

  // Cancel both delayed navigation and in-flight selections when the route changes.
  $effect(() => {
    void route.pathname;
    return cancelPendingAutoAdvance;
  });

  // A title that is already stored opens as its item.
  $effect(() => {
    const existingId = checkedPreview?.existing_item_id;
    if (checkedPreview && existingId != null) {
      goToItemView({ ...checkedPreview, id: existingId }, view, { replace: true });
    }
  });

  $effect(() => {
    if (isApiError(activeQuery.error) && activeQuery.error.status === 404)
      goToLibrary(uiState.sidebarTab);
  });
</script>

<DataStatus
  label={tmdbId ? "TMDB title" : "item"}
  error={activeQuery.error}
  loading={activeQuery.isFetching}
  hasData={!!(item ?? checkedPreview)}
  onretry={() => activeQuery.refetch()}
/>
{#if item || preview}
  <DetailPanel {item} {preview} {view} />
{/if}
