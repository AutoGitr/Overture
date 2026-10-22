<script lang="ts">
  import { createQuery, useQueryClient } from "@tanstack/svelte-query";
  import { Router } from "sv-router";
  import { onMount, tick } from "svelte";
  import {
    getPublicDatasetStatusOptions,
    getSettingsOptions,
    listItemsOptions,
  } from "./generated/rest/@tanstack/svelte-query.gen";
  import { realtimeTransport } from "./lib/realtime/transport";
  import type { NoticeTone } from "./lib/stores/notificationState.svelte";
  import { realtimeConnectionState } from "./lib/stores/realtimeConnectionState.svelte";
  import { uiState } from "./lib/stores/uiState.svelte";
  import { delayedFlag } from "./lib/utils/delayedFlag.svelte";
  import { errorMessage } from "./lib/utils/errors";

  import AppLoader from "./lib/components/AppLoader.svelte";
  import Header from "./lib/components/Header.svelte";
  import Notice from "./lib/components/Notice.svelte";
  import PinnedNotices from "./lib/components/PinnedNotices.svelte";
  import Sidebar from "./lib/components/Sidebar.svelte";

  import { POPUP_COMPONENTS } from "./lib/popups/registry";

  const queryClient = useQueryClient();

  let { onLogout }: { onLogout: () => void } = $props();

  /** The layout stays under the loader until its first loads have settled. */
  let ready = $state(false);

  const moviesOptions = listItemsOptions({ query: { media_type: "movie" } });
  const showOptions = listItemsOptions({ query: { media_type: "show" } });
  const settingsOptions = getSettingsOptions();
  const publicDatasetOptions = getPublicDatasetStatusOptions();
  const moviesQuery = createQuery(() => moviesOptions);
  const showQuery = createQuery(() => showOptions);
  const settingsQuery = createQuery(() => settingsOptions);
  const publicDatasetQuery = createQuery(() => publicDatasetOptions);

  let movies = $derived(moviesQuery.data?.items ?? []);
  let shows = $derived(showQuery.data?.items ?? []);
  let activeLibrary = $derived(uiState.sidebarTab === "movie" ? moviesQuery : showQuery);
  let loadErrors = $derived(
    [
      { name: "Movies", query: moviesQuery },
      { name: "Shows", query: showQuery },
      { name: "Settings", query: settingsQuery },
      { name: "OvertureDB", query: publicDatasetQuery },
    ].filter(({ query }) => query.isError),
  );
  let liveNotice = $derived.by((): { tone: NoticeTone; title: string; message: string } | null => {
    const { connected, error, lastSyncedAt } = realtimeConnectionState;
    if (error) {
      return {
        tone: "warning",
        title: "Live updates failed",
        message: `${error} Live data may be out of date.`,
      };
    }
    if (connected) return null;
    return lastSyncedAt === null
      ? {
          tone: "info",
          title: "Connecting to live updates",
          message: "Changes will appear shortly.",
        }
      : {
          tone: "warning",
          title: "Live connection interrupted",
          message: "Updates are being checked periodically.",
        };
  });
  // Reconnects that succeed straight away never surface a notice.
  const showLiveNotice = delayedFlag(() => liveNotice !== null);
  let ActivePopup = $derived(uiState.openPopup ? POPUP_COMPONENTS[uiState.openPopup] : null);

  function waitForHiddenLayoutFrame(): Promise<void> {
    if (document.hidden) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      // A tab can become hidden between frames, suspending animation callbacks.
      const finish = () => {
        clearTimeout(timer);
        cancelAnimationFrame(frame);
        resolve();
      };
      const timer = setTimeout(finish, 100);
      let frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(finish);
      });
    });
  }

  async function revealWhenInitialLayoutSettles(isCancelled: () => boolean): Promise<void> {
    // Query observers retain each failure so the UI can show it after startup.
    await Promise.allSettled([
      queryClient.fetchQuery(moviesOptions),
      queryClient.fetchQuery(showOptions),
      queryClient.fetchQuery(settingsOptions),
      queryClient.fetchQuery(publicDatasetOptions),
    ]);
    await tick();
    await waitForHiddenLayoutFrame();
    if (!isCancelled()) ready = true;
  }

  onMount(() => {
    let cancelled = false;
    void revealWhenInitialLayoutSettles(() => cancelled);
    realtimeTransport.connect();
    return () => {
      cancelled = true;
      realtimeTransport.disconnect();
    };
  });
</script>

<div class="main-layout">
  <Header {onLogout} />

  <PinnedNotices>
    {#each loadErrors as { name, query } (name)}
      <Notice
        tone="error"
        title="Couldn't load {name}"
        message={`${errorMessage(query.error, "Could not load data.")} ${
          query.data === undefined ? "Data is unavailable." : "Showing last loaded data."
        }`}
        action={{
          label: `Retry ${name}`,
          pendingLabel: "Retrying...",
          pending: query.isFetching,
          run: () => query.refetch(),
        }}
      />
    {/each}
    {#if liveNotice && showLiveNotice.current}
      <Notice
        {...liveNotice}
        action={{
          label: "Retry live updates",
          pendingLabel: "Refreshing...",
          pending: realtimeConnectionState.refreshing,
          run: () => realtimeTransport.retry(),
        }}
      />
    {/if}
  </PinnedNotices>

  <div class={["main-content", { "show-detail": uiState.mobileShowDetail }]}>
    <div class="sidebar-wrapper">
      <Sidebar
        {movies}
        {shows}
        totalMovies={movies.length}
        totalShows={shows.length}
        loading={activeLibrary.isPending && activeLibrary.isFetching}
        error={activeLibrary.isError && !activeLibrary.data
          ? "Library unavailable. Use Retry in the notification to reconnect."
          : ""}
      />
    </div>

    <div class="detail-wrapper">
      <Router />
    </div>
  </div>

  {#if ActivePopup}
    <ActivePopup />
  {/if}
</div>

{#if !ready}
  <div class="startup-overlay">
    <AppLoader />
  </div>
{/if}

<style>
  .startup-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
  }

  .main-layout {
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    position: relative;
  }

  .main-content {
    display: flex;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .sidebar-wrapper {
    display: flex;
    flex-shrink: 0;
    height: 100%;
  }

  .detail-wrapper {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
  }

  @media (max-width: 768px), (max-height: 500px) and (pointer: coarse) {
    /* Sidebar fills the full screen by default on mobile */
    .sidebar-wrapper {
      width: 100%;
      padding-bottom: var(--safe-area-bottom);
    }

    /* Detail hidden by default; revealed when show-detail is set */
    .detail-wrapper {
      display: none;
    }

    .main-content.show-detail .sidebar-wrapper {
      display: none;
    }

    .main-content.show-detail .detail-wrapper {
      display: flex;
      width: 100%;
      padding-bottom: var(--safe-area-bottom);
    }
  }
</style>
