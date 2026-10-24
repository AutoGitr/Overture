import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MediaItemRead } from "../../../generated/rest/types.gen";
import { WEBSOCKET_EVENTS } from "../../../generated/ws";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError, setUnauthorizedHandler } from "../../../lib/rest/transport";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { realtimeConnectionState } from "../../../lib/stores/realtimeConnectionState.svelte";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import { itemArtDisplayUrl } from "../../../lib/utils/artDisplay";
import { logEntry, loggedLines, mediaItem } from "../../helpers/fixtures";
import { FakeWebSocket } from "../../helpers/websocket";

const cache = vi.hoisted(() => ({
  invalidateTags: vi.fn(async () => {}),
  invalidateReconnectData: vi.fn(async () => {}),
  patchCollection: vi.fn(() => {}),
  invalidateSeasons: vi.fn(async () => {}),
  refreshItem: vi.fn(async () => {}),
  removeLibraryItem: vi.fn(() => {}),
  upsertLibraryItem: vi.fn<(item: MediaItemRead) => void>(),
}));

const bootstrap = vi.hoisted(() => ({
  loadRealtimeSnapshot: vi.fn(async (_signal: AbortSignal) => {}),
}));

vi.mock("../../../lib/rest/cache", () => cache);
vi.mock("../../../lib/realtime/bootstrap", () => bootstrap);

const epoch = "epoch-1";

function snapshot(sequence = 0, currentEpoch = epoch) {
  return {
    epoch: currentEpoch,
    sequence,
    event: "realtime.snapshot",
    data: {
      epoch: currentEpoch,
      sequence,
      server_time: new Date().toISOString(),
      jobs: [],
      downloads: [],
      public_dataset_status: {
        enabled: false,
        repo_url: "https://example.invalid/repo",
        catalog_url: "https://example.invalid/catalog",
      },
    },
  };
}

function serverEvent(sequence: number, event: string, data: unknown, currentEpoch = epoch) {
  return { epoch: currentEpoch, sequence, event, data };
}

async function loadTransport() {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const module = await import("../../../lib/realtime/transport");
  return module.realtimeTransport;
}

function openAndSync(socket: FakeWebSocket, sequence = 0) {
  socket.open();
  socket.receive(snapshot(sequence));
}

describe("realtimeTransport", () => {
  beforeEach(() => {
    FakeWebSocket.reset();
    queryClient.clear();
    cache.invalidateTags.mockClear();
    cache.invalidateReconnectData.mockClear();
    cache.patchCollection.mockClear();
    cache.invalidateSeasons.mockClear();
    cache.refreshItem.mockClear();
    cache.removeLibraryItem.mockClear();
    cache.upsertLibraryItem.mockClear();
    bootstrap.loadRealtimeSnapshot.mockReset();
    bootstrap.loadRealtimeSnapshot.mockResolvedValue(undefined);
    cache.invalidateReconnectData.mockResolvedValue(undefined);
    syncState.reset();
  });

  afterEach(async () => {
    const { realtimeTransport } = await import("../../../lib/realtime/transport");
    realtimeTransport.disconnect();
    setUnauthorizedHandler(null);
  });

  it("generates the realtime snapshot event", () => {
    expect(WEBSOCKET_EVENTS).toContain("realtime.snapshot");
  });

  it("connects to /ws and requests a resync on open", async () => {
    const transport = await loadTransport();
    transport.connect();
    FakeWebSocket.instances[0]?.open();

    expect(FakeWebSocket.instances[0]?.url).toBe("ws://localhost:3000/ws");
    expect(FakeWebSocket.instances[0]?.sent).toEqual([JSON.stringify({ event: "client.resync" })]);
  });

  it("uses REST snapshots only while the websocket is unavailable", async () => {
    vi.useFakeTimers();
    const transport = await loadTransport();
    transport.connect();

    expect(bootstrap.loadRealtimeSnapshot).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(5000);
    expect(bootstrap.loadRealtimeSnapshot).toHaveBeenCalledTimes(2);

    openAndSync(FakeWebSocket.instances[0]!);
    bootstrap.loadRealtimeSnapshot.mockClear();
    await vi.advanceTimersByTimeAsync(5000);

    expect(bootstrap.loadRealtimeSnapshot).not.toHaveBeenCalled();
  });

  it("exposes snapshot failures and clears them after a successful retry", async () => {
    vi.useFakeTimers();
    bootstrap.loadRealtimeSnapshot.mockRejectedValueOnce(
      new ApiError("Snapshot unavailable", 503, "snapshot-request"),
    );
    const transport = await loadTransport();
    transport.connect();
    await vi.advanceTimersByTimeAsync(0);
    expect(realtimeConnectionState.error).toContain("snapshot-request");
    expect(realtimeConnectionState.lastSyncedAt).toBeNull();
    await transport.retry();
    expect(realtimeConnectionState.error).toBe("");
    expect(realtimeConnectionState.lastSyncedAt).not.toBeNull();
  });

  it("does not overlap snapshot requests and cancels them on disconnect", async () => {
    vi.useFakeTimers();
    bootstrap.loadRealtimeSnapshot.mockImplementationOnce(
      (signal) =>
        new Promise((_, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const transport = await loadTransport();
    transport.connect();
    await vi.advanceTimersByTimeAsync(10000);
    expect(bootstrap.loadRealtimeSnapshot).toHaveBeenCalledOnce();
    expect(realtimeConnectionState.refreshing).toBe(true);
    transport.disconnect();
    await vi.advanceTimersByTimeAsync(0);
    expect(bootstrap.loadRealtimeSnapshot.mock.calls[0]?.[0].aborted).toBe(true);
    expect(realtimeConnectionState.error).toBe("");
    expect(realtimeConnectionState.refreshing).toBe(false);
  });

  it("reports authentication rejection once and stops reconnecting", async () => {
    vi.useFakeTimers();
    const expired = vi.fn();
    setUnauthorizedHandler(expired);
    const transport = await loadTransport();
    transport.connect();
    FakeWebSocket.instances[0]!.close(4001);
    await vi.advanceTimersByTimeAsync(60000);
    expect(expired).toHaveBeenCalledOnce();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(realtimeConnectionState.phase).toBe("disconnected");
  });

  it("ignores delayed callbacks from a previous connection", async () => {
    vi.useFakeTimers();
    const transport = await loadTransport();
    transport.connect();
    const previous = FakeWebSocket.instances[0]!;
    transport.disconnect();
    transport.connect();
    const current = FakeWebSocket.instances[1]!;
    openAndSync(current);
    previous.open();
    previous.receive(serverEvent(99, "sync.progress", { done: 99, total: 100 }));
    previous.onclose?.(new CloseEvent("close", { code: 4001 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(syncState.done).toBe(0);
    expect(realtimeConnectionState.connected).toBe(true);
  });

  it("reconnects when heartbeats arrive but the requested snapshot never does", async () => {
    vi.useFakeTimers();
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();
    for (let i = 0; i < 4; i++) {
      socket.receive({ event: "ping" });
      await vi.advanceTimersByTimeAsync(5000);
    }
    expect(socket.closed).toBe(true);
  });

  it("reports cache refresh failures after reconnect instead of claiming fresh data", async () => {
    vi.useFakeTimers();
    const transport = await loadTransport();
    transport.connect();
    await vi.advanceTimersByTimeAsync(0);
    cache.invalidateReconnectData.mockRejectedValueOnce(new ApiError("Library unavailable", 503));
    openAndSync(FakeWebSocket.instances[0]!);
    await vi.advanceTimersByTimeAsync(0);
    expect(realtimeConnectionState.error).toBe("Library unavailable");
    await transport.retry();
    expect(realtimeConnectionState.error).toBe("");
  });

  it("buffers sequenced events until the snapshot watermark arrives", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();
    socket.receive(
      serverEvent(2, "sync.progress", {
        done: 2,
        total: 3,
        log: logEntry("Added", "Replayed", "new"),
      }),
    );

    expect(syncState.done).toBe(0);

    socket.receive(snapshot(1));

    expect(syncState.running).toBe(true);
    expect(syncState.done).toBe(2);
    expect(loggedLines(syncState.log)).toEqual([logEntry("Added", "Replayed", "new")]);
  });

  it("drops buffered events already covered by the snapshot watermark", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();
    socket.receive(
      serverEvent(1, "sync.progress", {
        done: 1,
        total: 3,
        log: logEntry("Added", "Stale", "new"),
      }),
    );
    socket.receive(snapshot(1));

    expect(syncState.done).toBe(0);
    expect(syncState.log.total).toBe(0);
  });

  it("reconnects instead of silently dropping an overflowing event buffer", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.open();

    for (let sequence = 1; sequence <= 501; sequence += 1) {
      socket.receive(serverEvent(sequence, "sync.progress", { done: sequence, total: 501 }));
    }

    expect(socket.closed).toBe(true);
  });

  it("does not project a delayed snapshot older than the applied watermark", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);
    socket.receive(
      serverEvent(1, "sync.progress", {
        done: 1,
        total: 2,
        log: logEntry("Added", "Fresh", "new"),
      }),
    );

    socket.receive(snapshot());

    expect(syncState.done).toBe(1);
    expect(loggedLines(syncState.log)).toEqual([logEntry("Added", "Fresh", "new")]);
  });

  it("ignores malformed envelopes", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);

    socket.receive({ event: "sync.progress", data: { done: 1, total: 2 } });

    expect(syncState.done).toBe(0);
  });

  it("replaces projected state when the backend epoch changes", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);
    socket.receive(
      serverEvent(1, "sync.progress", { done: 1, total: 2, log: logEntry("Added", "Old", "new") }),
    );

    socket.receive(snapshot(0, "epoch-2"));
    socket.receive(
      serverEvent(
        1,
        "sync.progress",
        { done: 2, total: 2, log: logEntry("Added", "New", "new") },
        "epoch-2",
      ),
    );

    expect(syncState.done).toBe(2);
    expect(loggedLines(syncState.log)).toEqual([logEntry("Added", "New", "new")]);
  });

  it("applies entity cache policy after synchronization", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);
    const movie = mediaItem({
      id: 42,
      title: "Alien",
      media_type: "movie",
    });

    socket.receive(
      serverEvent(1, "library.item.upserted", { item: movie, source: "incremental_sync" }),
    );
    socket.receive(
      serverEvent(2, "collection.theme.updated", {
        has_theme: true,
        media_type: "movie",
        collection_id: 1,
        youtube_id: "abc123",
        youtube_title: "Collection Theme",
        youtube_duration: 120,
      }),
    );

    expect(cache.upsertLibraryItem).toHaveBeenCalledWith(movie);
    expect(cache.invalidateSeasons).toHaveBeenCalledWith(movie.id);
    expect(cache.patchCollection).toHaveBeenCalledWith(1, {
      has_theme: true,
      youtube_id: "abc123",
      youtube_title: "Collection Theme",
      youtube_duration: 120,
    });
  });

  it("defers full-sync library item updates until the terminal invalidation", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);
    const movie = mediaItem({
      id: 42,
      title: "Alien",
      media_type: "movie",
    });

    socket.receive(serverEvent(1, "library.item.upserted", { item: movie, source: "sync" }));

    expect(cache.upsertLibraryItem).not.toHaveBeenCalled();
    expect(cache.invalidateSeasons).not.toHaveBeenCalled();
  });

  it("applies realtime asset refreshes to cached library items", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);
    const movie = mediaItem({
      id: 42,
      title: "Alien",
      media_type: "movie",
      server_item_id: "provider-42",
      poster_hash: "poster-hash",
      poster_height: 1500,
      poster_url: null,
      poster_width: 1000,
      background_hash: "background-hash",
      background_height: 1080,
      background_url: "https://images.example/background.jpg",
      background_width: 1920,
      theme_file_hash: "theme-hash",
      theme_status: "complete",
      youtube_title: "Alien Theme",
      youtube_id: "abcDEF123_4",
    });

    socket.receive(
      serverEvent(1, "library.item.upserted", { item: movie, source: "incremental_sync" }),
    );

    expect(cache.upsertLibraryItem).toHaveBeenCalledTimes(1);
    const [upserted] = cache.upsertLibraryItem.mock.calls.at(0) ?? [];
    if (!upserted) throw new Error("Expected upsertLibraryItem to receive an item");
    expect(upserted.poster_hash).toBe("poster-hash");
    expect(upserted.theme_status).toBe("complete");
    expect(upserted.background_hash).toBe("background-hash");
    expect(upserted.youtube_id).toBe("abcDEF123_4");
    expect(itemArtDisplayUrl(upserted, "poster")).toBe(
      "/api/library/items/42/local-image/poster?t=poster-hash&size=display",
    );
    expect(cache.invalidateSeasons).toHaveBeenCalledWith(42);
  });

  it("invalidates backup data as soon as a backup completes", async () => {
    const transport = await loadTransport();
    transport.connect();
    const socket = FakeWebSocket.instances[0]!;
    openAndSync(socket);

    socket.receive(
      serverEvent(1, "backup.completed", {
        scheduled: false,
        filename: "overture-manual.db",
      }),
    );

    expect(cache.invalidateTags).toHaveBeenCalledWith(["backups"]);
  });

  it.each(["completed", "cancelled"])(
    "removes a %s download without refetching its item",
    async (status) => {
      const transport = await loadTransport();
      transport.connect();
      const socket = FakeWebSocket.instances[0]!;
      openAndSync(socket);
      downloadState.trackQueuedItemJob({ jobId: "unrelated", mediaItemId: 43, jobType: "theme" });
      const target = {
        target_type: "item",
        media_item_id: 42,
        job_type: "theme",
      };

      socket.receive(
        serverEvent(1, "download.progress", {
          job: { id: "download-1", kind: "download", status: "progress", target },
          percent: 85,
          stage: "transcoding",
        }),
      );
      expect(downloadState.activeCount).toBe(2);
      expect(downloadState.getJobsForItem(42)[0]?.stage).toBe("transcoding");

      socket.receive(
        serverEvent(2, `download.${status}`, {
          job: {
            id: "download-1",
            kind: "download",
            status,
            target,
          },
          percent: 100,
        }),
      );

      expect(cache.refreshItem).not.toHaveBeenCalled();
      expect(downloadState.getJobsForItem(42)).toEqual([]);
      expect(downloadState.isDownloadingType(42, "theme")).toBe(false);
      expect(downloadState.activeCount).toBe(1);
      expect(downloadState.getJobsForItem(43)[0]?.job_id).toBe("unrelated");
    },
  );

  it("retries a connection that never opens while REST fallback remains available", async () => {
    vi.useFakeTimers();
    const transport = await loadTransport();
    transport.connect();
    await vi.advanceTimersByTimeAsync(21000);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(bootstrap.loadRealtimeSnapshot).toHaveBeenCalled();
    transport.disconnect();
  });

  it("backs off reconnects and invalidates REST tags after the new snapshot", async () => {
    vi.useFakeTimers();
    const transport = await loadTransport();
    transport.connect();
    const first = FakeWebSocket.instances[0]!;
    openAndSync(first);
    cache.invalidateReconnectData.mockClear();
    first.close();

    await vi.advanceTimersByTimeAsync(1000);
    const second = FakeWebSocket.instances[1]!;
    openAndSync(second);

    expect(cache.invalidateReconnectData).toHaveBeenCalled();

    transport.disconnect();
    second.close();
    await vi.advanceTimersByTimeAsync(2000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
