import { getPublicDatasetStatusOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { PublicDatasetStatus } from "../../generated/rest/types.gen";
import type { DownloadJobEvent, ServerWebSocketDataMessage } from "../../generated/ws";
import {
  applyBulkItemOperation,
  invalidateReconnectData,
  invalidateSeasons,
  invalidateTags,
  patchCollection,
  refreshItem,
  removeLibraryItem,
  upsertLibraryItem,
} from "../rest/cache";
import { queryClient } from "../rest/queryClient";
import { realtimeConnectionState } from "../stores/realtimeConnectionState.svelte";
import { errorMessage, isAbortError } from "../utils/errors";

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

/** Store the dataset status the snapshot carried, for the views that read it. */
export function storePublicDatasetStatus(status: PublicDatasetStatus): void {
  queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, status);
}

/** Keep the REST caches consistent with one applied realtime event. */
export function applyRestCachePolicy(message: ServerWebSocketDataMessage): void {
  if (message.event === "collection.theme.updated") {
    patchCollection(message.data.server_id, {
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

  if (message.event === "public-dataset.updated") {
    storePublicDatasetStatus(message.data);
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
    void invalidateTags(["library"]);
  }
}
