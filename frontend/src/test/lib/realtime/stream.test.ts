import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { serverClock } from "../../../lib/realtime/serverClock";
import { client } from "../../../generated/rest/client.gen";
import { realtimeStream } from "../../../lib/realtime/stream";
import { queryClient } from "../../../lib/rest/queryClient";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { appUpdate } from "../../../lib/stores/appUpdate.svelte";
import { mediaServerState } from "../../../lib/stores/mediaServerState.svelte";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import {
  catalogStatus,
  logEntry,
  loggedLines,
  realtimeSnapshot,
  syncEvent,
  wsMessage,
} from "../../helpers/fixtures";

function snapshot(sequence: number) {
  return realtimeSnapshot({
    sequence,
    catalog_status: catalogStatus({ enabled: false }),
  });
}

describe("realtime stream reconciliation", () => {
  beforeEach(() => {
    queryClient.clear();
    client.setConfig({ baseUrl: location.origin });
    realtimeStream.reset();
    downloadState.replaceSnapshot([]);
    syncState.reset();
  });

  it("reconciles a job the server does not know about from a same-sequence snapshot", () => {
    // A same-sequence snapshot must reconcile optimistic jobs too.
    realtimeStream.applySnapshot(snapshot(7));
    downloadState.trackQueuedItemJob({
      jobId: "ghost-job",
      mediaItemId: 42,
      jobType: "art",
      artType: "poster",
    });

    expect(downloadState.isDownloadingType(42, "art")).toBe(true);

    expect(realtimeStream.applySnapshot(snapshot(7))).toBe(true);

    expect(downloadState.activeCount).toBe(0);
  });

  it("keeps a running job's log across a snapshot of the same epoch", () => {
    realtimeStream.applySnapshot(snapshot(1));
    const added = logEntry("Added", "Alien", "new");
    realtimeStream.applyEvent(
      wsMessage("sync.progress", syncEvent({ done: 1, total: 3, log: added }), 2),
    );
    const resumed = logEntry("Updated", "Aliens", "changed");

    realtimeStream.applySnapshot({
      ...snapshot(5),
      jobs: [
        {
          event: "sync.progress",
          data: { done: 2, total: 3, log: { ...resumed } },
        },
      ],
    });

    expect(loggedLines(syncState.log)).toEqual([added, resumed]);
    expect(syncState.done).toBe(2);
  });

  it("forgets job state and tells the app update when the server starts a new epoch", () => {
    const observeServer = vi.spyOn(appUpdate, "observeServer").mockImplementation(() => {});
    const version = snapshot(1).app_version;
    realtimeStream.applySnapshot(snapshot(1));
    syncState.handleProgress(syncEvent({ done: 1, log: logEntry("Added", "Alien", "new") }));
    expect(observeServer).toHaveBeenLastCalledWith(version, false);

    // A disconnect clears the connection watermark before the restarted server answers.
    realtimeStream.reset();
    realtimeStream.applySnapshot({ ...snapshot(0), epoch: "epoch-2" });

    expect(syncState.log.total).toBe(0);
    expect(syncState.status).toBe("idle");
    expect(observeServer).toHaveBeenLastCalledWith(version, true);
  });

  it("keeps projecting events after the REST cache has been collected", () => {
    realtimeStream.applySnapshot(snapshot(1));
    queryClient.clear();

    const applied = realtimeStream.applyEvent(
      wsMessage(
        "sync.progress",
        syncEvent({ done: 3, total: 10, log: logEntry("Added", "Alien", "still arriving") }),
        2,
      ),
    );

    expect(applied).toBe(true);
    expect(syncState.done).toBe(3);
    expect(loggedLines(syncState.log)).toEqual([logEntry("Added", "Alien", "still arriving")]);
  });

  it("follows the media server's state from snapshots and events", () => {
    realtimeStream.applySnapshot(snapshot(1));
    expect(mediaServerState.down).toEqual([]);

    realtimeStream.applyEvent(
      wsMessage(
        "media-server.status",
        { server_id: 1, title: "Plex", state: "rejected", message: "check the key" },
        2,
      ),
    );
    expect(mediaServerState.down.map((server) => server.message)).toEqual(["check the key"]);

    realtimeStream.applySnapshot(snapshot(3));
    expect(mediaServerState.down).toEqual([]);
  });

  it("rejects a snapshot that is strictly behind the applied sequence", () => {
    vi.useFakeTimers({ toFake: ["performance"] });
    realtimeStream.applySnapshot({ ...snapshot(9), server_time: "2026-06-02T10:00:00Z" });
    vi.advanceTimersByTime(2000);

    expect(
      realtimeStream.applySnapshot({ ...snapshot(4), server_time: "2026-06-02T09:00:00Z" }),
    ).toBe(false);
    expect(serverClock.isoNow()).toBe("2026-06-02T10:00:02.000Z");
  });
});

describe("realtime stream ordering for any arrival order", () => {
  it("applies exactly the snapshot epoch's events newer than the last one applied", () => {
    const arrival = fc.record({
      epoch: fc.constantFrom("epoch-1", "epoch-0"),
      sequence: fc.integer({ min: -2, max: 60 }),
    });
    fc.assert(
      fc.property(fc.nat({ max: 40 }), fc.array(arrival, { maxLength: 30 }), (start, arrivals) => {
        realtimeStream.reset();
        realtimeStream.applySnapshot(snapshot(start));
        let watermark = start;
        for (const { epoch, sequence } of arrivals) {
          const expected = epoch === "epoch-1" && sequence > watermark;
          const message = wsMessage("sync.progress", syncEvent(), sequence, epoch);
          expect(realtimeStream.applyEvent(message)).toBe(expected);
          if (expected) watermark = sequence;
        }
        // A snapshot behind what is applied is refused; one at or past it is adopted.
        expect(realtimeStream.applySnapshot(snapshot(watermark - 1))).toBe(false);
        expect(realtimeStream.applySnapshot(snapshot(watermark))).toBe(true);
      }),
    );
  });
});
