import { beforeEach, describe, expect, it } from "vitest";
import { client } from "../../../generated/rest/client.gen";
import { realtimeStream } from "../../../lib/realtime/stream";
import { queryClient } from "../../../lib/rest/queryClient";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import {
  logEntry,
  loggedLines,
  publicDatasetStatus,
  realtimeSnapshot,
  wsMessage,
} from "../../helpers/fixtures";

function snapshot(sequence: number) {
  return realtimeSnapshot({
    sequence,
    public_dataset_status: publicDatasetStatus({ enabled: false }),
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
    realtimeStream.applyEvent(wsMessage("sync.progress", { done: 1, total: 3, log: added }, 2));
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

  it("forgets job state when the server starts a new epoch", () => {
    realtimeStream.applySnapshot(snapshot(1));
    syncState.handleProgress({ done: 1, log: logEntry("Added", "Alien", "new") });

    realtimeStream.applySnapshot({ ...snapshot(0), epoch: "epoch-2" });

    expect(syncState.log.total).toBe(0);
    expect(syncState.status).toBe("idle");
  });

  it("keeps projecting events after the REST cache has been collected", () => {
    realtimeStream.applySnapshot(snapshot(1));
    queryClient.clear();

    const applied = realtimeStream.applyEvent(
      wsMessage(
        "sync.progress",
        { done: 3, total: 10, log: logEntry("Added", "Alien", "still arriving") },
        2,
      ),
    );

    expect(applied).toBe(true);
    expect(syncState.done).toBe(3);
    expect(loggedLines(syncState.log)).toEqual([logEntry("Added", "Alien", "still arriving")]);
  });

  it("rejects a snapshot that is strictly behind the applied sequence", () => {
    realtimeStream.applySnapshot(snapshot(9));

    expect(realtimeStream.applySnapshot(snapshot(4))).toBe(false);
  });
});
