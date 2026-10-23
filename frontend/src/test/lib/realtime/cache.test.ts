import { beforeEach, describe, expect, it, vi } from "vitest";
import { getPublicDatasetStatusOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { DownloadJobEvent } from "../../../generated/ws";
import {
  applyRestCachePolicy,
  refreshRemovedDownloadTargets,
  reportRefreshFailure,
} from "../../../lib/realtime/cache";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { realtimeConnectionState } from "../../../lib/stores/realtimeConnectionState.svelte";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import {
  itemDownload,
  mediaItem,
  publicDatasetStatus,
  wsMessage as message,
} from "../../helpers/fixtures";

const rest = vi.hoisted(() => ({
  applyBulkItemOperation: vi.fn(),
  invalidateReconnectData: vi.fn(),
  invalidateSeasons: vi.fn(),
  invalidateTags: vi.fn(),
  patchCollection: vi.fn(),
  refreshItem: vi.fn(),
  removeLibraryItem: vi.fn(),
  upsertLibraryItem: vi.fn(),
}));
vi.mock("../../../lib/rest/cache", () => rest);

function collectionDownload(id: string): DownloadJobEvent {
  return {
    percent: null,
    stage: null,
    step: null,
    steps: null,
    unchanged: null,
    job: {
      id,
      kind: "download",
      status: "completed",
      target: {
        target_type: "collection_theme",
        collection_id: 1,
        title: "Saga",
      },
      error: null,
    },
  };
}

describe("realtime REST cache policy", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    queryClient.clear();
    realtimeConnectionState.reset();
    syncState.reset();
    rest.refreshItem.mockResolvedValue(undefined);
    rest.invalidateSeasons.mockResolvedValue(undefined);
    rest.invalidateTags.mockResolvedValue(undefined);
    rest.invalidateReconnectData.mockResolvedValue(undefined);
  });

  it("invalidates collections and catalog links when matching or membership changes", () => {
    applyRestCachePolicy(message("collections.changed", null));
    expect(rest.invalidateTags).toHaveBeenCalledWith(["collections", "public-dataset", "library"]);
  });

  it("refreshes individual collection changes while coalescing full sync updates", () => {
    applyRestCachePolicy(message("collection.updated", { collection_id: 1 }));
    expect(rest.invalidateTags).toHaveBeenCalledExactlyOnceWith([
      "collections",
      "public-dataset",
      "library",
    ]);
    rest.invalidateTags.mockClear();
    syncState.handleStarted({});
    applyRestCachePolicy(message("collection.updated", { collection_id: 2 }));
    expect(rest.invalidateTags).not.toHaveBeenCalled();
    applyRestCachePolicy(message("collections.changed", null));
    expect(rest.invalidateTags).toHaveBeenCalledTimes(1);
  });

  it("patches a collection's theme without its absent YouTube details", () => {
    applyRestCachePolicy(
      message("collection.theme.updated", {
        collection_id: 1,
        media_type: "movie",
        has_theme: true,
        theme_status: "complete",
      }),
    );

    expect(rest.patchCollection).toHaveBeenCalledWith(1, {
      has_theme: true,
      youtube_id: null,
      youtube_title: null,
      youtube_duration: null,
      theme_status: "complete",
    });
  });

  it("stores an item a user action changed, but leaves sync's items to the sync refresh", () => {
    const item = mediaItem({ id: 4 });

    applyRestCachePolicy(message("library.item.upserted", { item, source: "sync" }));
    expect(rest.upsertLibraryItem).not.toHaveBeenCalled();

    applyRestCachePolicy(message("library.item.upserted", { item, source: "match" }));
    expect(rest.upsertLibraryItem).toHaveBeenCalledWith(item);
    expect(rest.invalidateSeasons).toHaveBeenCalledWith(4);
  });

  it("applies bulk changes and removals to the library", () => {
    applyRestCachePolicy(
      message("library.items.changed", { item_ids: [1, 2], operation: "monitor" }),
    );
    applyRestCachePolicy(message("library.item.removed", { media_item_id: 3 }));

    expect(rest.applyBulkItemOperation).toHaveBeenCalledWith({
      item_ids: [1, 2],
      operation: "monitor",
    });
    expect(rest.removeLibraryItem).toHaveBeenCalledWith(3);
  });

  it("stores a new dataset status and re-reads what depends on it", () => {
    const status = publicDatasetStatus({ enabled: false });

    applyRestCachePolicy(message("public-dataset.updated", status));

    expect(queryClient.getQueryData(getPublicDatasetStatusOptions().queryKey)).toEqual(status);
    expect(rest.invalidateReconnectData).toHaveBeenCalledOnce();
  });

  it("re-reads an updated item and then its seasons", async () => {
    applyRestCachePolicy(message("item.updated", { media_item_id: 9 }));

    await vi.waitFor(() => expect(rest.invalidateSeasons).toHaveBeenCalledWith(9));
    expect(rest.refreshItem).toHaveBeenCalledWith(9);
  });

  it.each(["download.completed", "download.failed", "download.cancelled"] as const)(
    "leaves entity data to domain events after %s",
    (event) => {
      applyRestCachePolicy(message(event, itemDownload("a", 5, "completed")));
      applyRestCachePolicy(message(event, collectionDownload("b")));

      expect(rest.invalidateSeasons).not.toHaveBeenCalled();
      expect(rest.refreshItem).not.toHaveBeenCalled();
      expect(rest.invalidateTags).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["backup.completed", ["backups"]],
    ["backup.failed", ["backups"]],
    ["sync.completed", ["library", "collections", "sync", "tmdb"]],
    ["sync.stopped", ["library", "collections", "sync", "tmdb"]],
    ["sync.failed", ["library", "collections", "sync", "tmdb"]],
    ["match.completed", ["library"]],
    ["match.stopped", ["library"]],
    ["match.failed", ["library"]],
    ["theme.completed", ["library", "collections"]],
    ["theme.stopped", ["library", "collections"]],
    ["theme.failed", ["library", "collections"]],
  ] as const)("marks the data a %s event changes stale", (event, tags) => {
    applyRestCachePolicy(message(event, {}));

    expect(rest.invalidateTags).toHaveBeenCalledExactlyOnceWith(tags);
  });

  it("leaves the caches alone for progress events", () => {
    applyRestCachePolicy(message("sync.progress", { done: 1 }));

    expect(Object.values(rest).every((fn) => fn.mock.calls.length === 0)).toBe(true);
  });

  it("refreshes the targets of downloads that ended while the client was away", async () => {
    const stillRunning = itemDownload("running", 1, "completed");

    refreshRemovedDownloadTargets(
      [
        stillRunning,
        itemDownload("ended", 2, "completed"),
        itemDownload("second-slot", 2, "completed"),
        collectionDownload("theme"),
        collectionDownload("other-theme"),
      ],
      [stillRunning],
    );

    await vi.waitFor(() => expect(rest.refreshItem).toHaveBeenCalledWith(2));
    expect(rest.refreshItem).toHaveBeenCalledTimes(1);
    expect(rest.invalidateTags).toHaveBeenCalledExactlyOnceWith(["collections"]);
  });
});

describe("live refresh failures", () => {
  beforeEach(() => realtimeConnectionState.reset());

  it("surface on the live connection", () => {
    reportRefreshFailure(new ApiError("Item unavailable", 503));

    expect(realtimeConnectionState.error).toBe("Item unavailable");
  });

  it("ignore a refresh that was cancelled", () => {
    reportRefreshFailure(Object.assign(new Error("Aborted"), { name: "AbortError" }));

    expect(realtimeConnectionState.error).toBe("");
  });

  it("reach the live connection when an item refresh fails", async () => {
    vi.resetAllMocks();
    rest.refreshItem.mockRejectedValue(new ApiError("Item unavailable", 503));

    applyRestCachePolicy(message("item.updated", { media_item_id: 9 }));

    await vi.waitFor(() => expect(realtimeConnectionState.error).toBe("Item unavailable"));
    expect(rest.invalidateSeasons).not.toHaveBeenCalled();
  });
});
