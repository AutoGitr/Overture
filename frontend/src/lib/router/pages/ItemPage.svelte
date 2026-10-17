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
  import { collectionState } from "../../stores/collectionState.svelte";
  import { selectedState } from "../../stores/selectedState.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { uiState } from "../../stores/uiState.svelte";
  import { cancelPendingAutoAdvance, preloadNextItem } from "../../utils/autoAdvance";
  import { parseItemSlug } from "../../utils/slug";
  import { goToItemView, goToLibrary, route, type ItemView } from "../routes";

  let slug = $derived(parseItemSlug(route.params.itemSlug));
  let itemId = $derived(slug?.kind === "item" ? slug.id : 0);
  let tmdbId = $derived(slug?.kind === "tmdb" ? slug.tmdbId : 0);

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

  let item = $derived(itemQuery.data ?? null);
  // A stale cached title may since have been stored, so it waits for the
  // re-check rather than opening as new; a fresh one opens at once.
  let preview = $derived(
    previewQuery.data?.tmdb_id === tmdbId &&
      previewQuery.data.media_type === uiState.sidebarTab &&
      (previewQuery.isFetchedAfterMount || !previewQuery.isStale)
      ? previewQuery.data
      : null,
  );

  /** The detail view the URL names (art/themes/sub-tab/season). */
  let view = $derived.by((): ItemView => {
    const pathname = route.pathname;
    if (pathname.endsWith("/themes")) {
      return { mode: "themes", artSubTab: "poster", drillSeasonNum: null };
    }
    if (!pathname.includes("/art")) {
      // Bare item route - fall back to the user's configured default tab.
      return { mode: settingsState.initial_tab, artSubTab: "poster", drillSeasonNum: null };
    }
    const seasonNum = route.params.seasonNum;
    if (seasonNum) return { mode: "art", artSubTab: "seasons", drillSeasonNum: Number(seasonNum) };
    const subtab = route.params.subtab;
    return {
      mode: "art",
      artSubTab: subtab === "background" || subtab === "seasons" ? subtab : "poster",
      drillSeasonNum: null,
    };
  });

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

  // An item and a collection can never be selected at the same time.
  $effect(() => {
    if (collectionState.selectedCollection) collectionState.selectCollection(null);
  });

  // Keep the selection store in sync with whichever item or title the URL points to.
  $effect(() => {
    if (tmdbId) {
      if (!preview || preview.tmdb_id !== tmdbId) {
        selectedState.selectItem(null);
        return;
      }
      if (preview.existing_item_id !== null) {
        // The title is already stored: open the item instead.
        goToItemView({ ...preview, id: preview.existing_item_id }, view, { replace: true });
        return;
      }
      if (
        selectedState.preview?.tmdb_id !== preview.tmdb_id ||
        selectedState.preview.media_type !== preview.media_type
      )
        selectedState.selectPreview(preview);
      uiState.mobileShowDetail = true;
      return;
    }
    // TanStack Query can briefly retain the previous route's data while the
    // dynamic query key changes. Never let that stale item reopen the mobile
    // detail pane after navigation has already moved to another library.
    if (!item || item.id !== itemId) {
      selectedState.selectItem(null);
      return;
    }
    if (selectedState.selectedItemId !== item.id) {
      selectedState.selectItem(item);
    } else {
      selectedState.updateItemData(item);
    }
    uiState.mobileShowDetail = true;
  });

  // Mirror the matched sub-route into the detail view state, so DetailPanel
  // renders exactly what the URL says.
  $effect(() => {
    if (!selectedState.subject) return;
    selectedState.mode = view.mode;
    selectedState.artSubTab = view.artSubTab;
    selectedState.drillSeasonNum = view.drillSeasonNum;
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
  hasData={!!(tmdbId ? preview : item)}
  onretry={() => activeQuery.refetch()}
/>
{#if (item && item.id === itemId) || (preview && preview.tmdb_id === tmdbId && preview.existing_item_id === null)}
  <DetailPanel />
{/if}
