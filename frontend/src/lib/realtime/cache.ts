import { getCatalogStatusOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CatalogStatus } from "../../generated/rest/types.gen";
import type { DownloadJobEvent, ServerWebSocketDataMessage } from "../../generated/ws";
import {
  applyBulkItemOperation,
  invalidateReconnectData,
  invalidateSeasons,
  invalidateTags,
  observeLibrary,
  patchCollection,
  refreshItem,
  removeLibraryItem,
  upsertLibraryItem,
} from "../rest/cache";
import { queryClient } from "../rest/queryClient";
import { goToLibrary, routedItemId } from "../router/routes";
import { artPreviewState } from "../stores/artPreviewState.svelte";
import { syncState } from "../stores/jobStates.svelte";
import { realtimeConnectionState } from "../stores/realtimeConnectionState.svelte";
import { uiState } from "../stores/uiState.svelte";
import { errorMessage, isAbortError } from "../utils/errors";

/** Keep the art preview and the open item in step with the library. */
export function followLibrary(): void {
  observeLibrary({
    itemUpdated: (item) => artPreviewState.itemUpdated(item),
    itemsRemoved: (isGone) => {
      const openId = routedItemId();
      if (openId !== null && isGone(openId)) goToLibrary(uiState.sidebarTab);
    },
  });
}

export function reportRefreshFailure(error: unknown): void {
  if (!isAbortError(error)) {
    realtimeConnectionState.error = errorMessage(
      error,
      "Could not refresh live data. Please retry.",
    );
  }
}

/** Re-read one item and mark its seasons stale. */
function refreshItemAndSeasons(itemId: number): void {
  void refreshItem(itemId)
    .then(() => invalidateSeasons(itemId))
    .catch(reportRefreshFailure);
}

/** Re-read the targets of downloads that ended while this client was away. */
export function refreshRemovedDownloadTargets(
  previous: DownloadJobEvent[],
  next: DownloadJobEvent[],
): void {
  const active = new Set(next.map((event) => event.job.id));
  const items = new Set<number>();
  let collectionsChanged = false;
  for (const event of previous) {
    if (active.has(event.job.id)) continue;
    const target = event.job.target;
    if (target.target_type === "item") items.add(target.media_item_id);
    else collectionsChanged = true;
  }
  for (const itemId of items) refreshItemAndSeasons(itemId);
  if (collectionsChanged) void invalidateTags(["collections"]).catch(reportRefreshFailure);
}

/** Store the catalog status the snapshot carried, for the views that read it. */
export function storeCatalogStatus(status: CatalogStatus): void {
  queryClient.setQueryData(getCatalogStatusOptions().queryKey, status);
}

/** Keep the REST caches consistent with one applied realtime event. */
export function applyRestCachePolicy(message: ServerWebSocketDataMessage): void {
  if (
    message.event === "collections.changed" ||
    (message.event === "collection.updated" && !syncState.running)
  ) {
    void invalidateTags(["collections", "catalog", "library"]);
  }
  if (message.event === "collection.monitored") {
    patchCollection(message.data.collection_id, { monitored: message.data.monitored });
  }
  if (message.event === "collection.theme.updated") {
    patchCollection(message.data.collection_id, {
      has_theme: message.data.has_theme,
      youtube_id: message.data.youtube_id ?? null,
      youtube_title: message.data.youtube_title ?? null,
      youtube_duration: message.data.youtube_duration ?? null,
      theme_status: message.data.theme_status,
    });
  }

  if (message.event === "library.item.upserted") {
    if (message.data.source !== "sync") {
      upsertLibraryItem(message.data.item);
      void invalidateSeasons(message.data.item.id).catch(reportRefreshFailure);
    }
  }

  if (message.event === "library.items.changed") {
    applyBulkItemOperation(message.data);
  }

  if (message.event === "library.item.removed") {
    removeLibraryItem(message.data.media_item_id);
  }

  if (message.event === "catalog.updated") {
    storeCatalogStatus(message.data);
    void invalidateReconnectData().catch(reportRefreshFailure);
  }

  if (message.event === "item.updated") {
    refreshItemAndSeasons(message.data.media_item_id);
  }

  if (message.event === "backup.completed" || message.event === "backup.failed") {
    void invalidateTags(["backups"]);
  }

  if (
    message.event === "sync.completed" ||
    message.event === "sync.stopped" ||
    message.event === "sync.failed"
  ) {
    // Sync can store or remove items, which TMDB answers name.
    void invalidateTags(["library", "collections", "sync", "tmdb"]);
  }

  if (
    message.event === "match.completed" ||
    message.event === "match.stopped" ||
    message.event === "match.failed" ||
    message.event === "theme.completed" ||
    message.event === "theme.stopped" ||
    message.event === "theme.failed"
  ) {
    void invalidateTags(
      message.event.startsWith("theme.") ? ["library", "collections"] : ["library"],
    );
  }
}
