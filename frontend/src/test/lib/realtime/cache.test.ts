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
    unchanged: null,
    job: {
      id,
      kind: "download",
      status: "completed",
      target: {
        target_type: "collection_theme",
        collection_server_id: "coll",
        media_type: "movie",
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
    rest.refreshItem.mockResolvedValue(undefined);
    rest.invalidateSeasons.mockResolvedValue(undefined);
    rest.invalidateTags.mockResolvedValue(undefined);
    rest.invalidateReconnectData.mockResolvedValue(undefined);
  });

  it("patches a collection's theme without its absent YouTube details", () => {
    applyRestCachePolicy(
      message("collection.theme.updated", {
        server_id: "coll",
        media_type: "movie",
        has_theme: true,
        theme_status: "complete",
      }),
    );

    expect(rest.patchCollection).toHaveBeenCalledWith("coll", {
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
    "re-reads what a %s download wrote to",
    async (event) => {
      applyRestCachePolicy(message(event, itemDownload("a", 5, "completed")));
      applyRestCachePolicy(message(event, collectionDownload("b")));

      await vi.waitFor(() => expect(rest.invalidateSeasons).toHaveBeenCalledWith(5));
      expect(rest.refreshItem).toHaveBeenCalledWith(5);
      expect(rest.invalidateTags).toHaveBeenCalledWith(["collections"]);
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
    ["theme.completed", ["library"]],
    ["theme.stopped", ["library"]],
    ["theme.failed", ["library"]],
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
      [stillRunning, itemDownload("ended", 2, "completed"), collectionDownload("theme")],
      [stillRunning],
    );

    await vi.waitFor(() => expect(rest.refreshItem).toHaveBeenCalledWith(2));
    expect(rest.refreshItem).not.toHaveBeenCalledWith(1);
    expect(rest.invalidateTags).toHaveBeenCalledWith(["collections"]);
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
