import { getCatalogStatusOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CatalogStatus } from "../../generated/rest/types.gen";
import {
  routeServerWebSocketMessage,
  type DownloadJobEvent,
  type ServerWebSocketDataMessage,
  type WebSocketHandlerMap,
} from "../../generated/ws";
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

/** Invalidate *tags* once an event says what they hold changed. */
function invalidating(tags: Parameters<typeof invalidateTags>[0]) {
  return () => void invalidateTags(tags);
}

/** Sync can store or remove items, which TMDB answers name. */
const AFTER_SYNC = invalidating(["library", "collections", "sync", "tmdb"]);
const AFTER_MATCH = invalidating(["library"]);
const AFTER_THEMES = invalidating(["library", "collections"]);
const AFTER_BACKUP = invalidating(["backups"]);

/** What each event changes in the REST cache; events left out change nothing there. */
const CACHE_POLICY: Partial<WebSocketHandlerMap> = {
  "collections.changed": invalidating(["collections", "catalog", "library"]),
  "collection.updated": (data) => {
    // The library lists hold every title, so they are read again only for a
    // change to the titles a collection links.
    if (!syncState.running)
      void invalidateTags(
        data.titles ? ["collections", "catalog", "library"] : ["collections", "catalog"],
      );
  },
  "collection.monitored": (data) =>
    patchCollection(data.collection_id, { monitored: data.monitored }),
  "library.item.upserted": (data) => {
    if (data.source === "sync") return;
    upsertLibraryItem(data.item);
    void invalidateSeasons(data.item.id).catch(reportRefreshFailure);
  },
  "library.items.changed": (data) => applyBulkItemOperation(data),
  "library.item.removed": (data) => removeLibraryItem(data.media_item_id),
  "catalog.updated": (data) => {
    storeCatalogStatus(data);
    void invalidateReconnectData().catch(reportRefreshFailure);
  },
  "item.updated": (data) => refreshItemAndSeasons(data.media_item_id),
  "backup.completed": AFTER_BACKUP,
  "backup.failed": AFTER_BACKUP,
  "sync.completed": AFTER_SYNC,
  "sync.stopped": AFTER_SYNC,
  "sync.failed": AFTER_SYNC,
  "match.completed": AFTER_MATCH,
  "match.stopped": AFTER_MATCH,
  "match.failed": AFTER_MATCH,
  "theme.completed": AFTER_THEMES,
  "theme.stopped": AFTER_THEMES,
  "theme.failed": AFTER_THEMES,
};

/** Keep the REST caches consistent with one applied realtime event. */
export function applyRestCachePolicy(message: ServerWebSocketDataMessage): void {
  routeServerWebSocketMessage(message, CACHE_POLICY);
}
