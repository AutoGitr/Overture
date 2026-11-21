import type { JobOutcome } from "../../../generated/ws";
import { beforeEach, describe, expect, it } from "vitest";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import { jobMetadata, logEntry, loggedLines, syncEvent } from "../../helpers/fixtures";

describe("syncState", () => {
  beforeEach(() => syncState.reset());

  it("handles lifecycle events and completion progress", () => {
    syncState.handleStarted(syncEvent({ total: 2, started_at: "start" }));
    const added = logEntry("Added", "Alien", "new library item");
    const removed = logEntry("Removed", "Aliens", "no longer on the media server");
    syncState.handleProgress(syncEvent({ done: 1, log: added, log_targets: { Added: 1 } }));
    syncState.handleCompleted(
      syncEvent({
        done: 2,
        total: 2,
        log: removed,
        finished_at: "finish",
        log_targets: { Added: 2, Unchanged: 0 },
      }),
    );

    expect(syncState.running).toBe(false);
    expect(syncState.count("Added")).toBe(2);
    expect(syncState.done).toBe(2);
    expect(syncState.progress).toBe(100);
    expect(loggedLines(syncState.log)).toEqual([added, removed]);
    expect(syncState.finished_at).toBe("finish");
  });

  it("zeroes its own counters on start", () => {
    syncState.handleProgress(
      syncEvent({ log_targets: { Added: 9, Updated: 9, Unchanged: 9, Removed: 9 } }),
    );

    syncState.handleStarted(syncEvent({ total: 3 }));

    expect(syncState.count("Added") + syncState.count("Removed")).toBe(0);
    expect(syncState.total).toBe(3);
  });

  it("keeps counters the first progress event does not carry", () => {
    // The first progress event of a run reports only a log line, so the
    // store must hold the zeros it was just reset to rather than go blank.
    syncState.handleStarted(syncEvent({ total: 3 }));
    const started = logEntry("Started", "Sync", "reading libraries from Plex");
    syncState.handleProgress(syncEvent({ log: started }));

    expect(syncState.count("Added")).toBe(0);
    expect(syncState.count("Unchanged")).toBe(0);
    expect(loggedLines(syncState.log)).toEqual([started]);
  });

  it("carries the authoritative terminal counts", () => {
    syncState.handleStarted(syncEvent({ total: 4 }));
    syncState.handleProgress(syncEvent({ done: 2, log_targets: { Added: 2 } }));

    syncState.handleCompleted(
      syncEvent({
        done: 4,
        total: 4,
        finished_at: "finish",
        log_targets: { Added: 2, Updated: 1, Unchanged: 1, Removed: 1 },
      }),
    );

    expect(
      ["Added", "Updated", "Unchanged", "Removed"].map((outcome) =>
        syncState.count(outcome as JobOutcome),
      ),
    ).toEqual([2, 1, 1, 1]);
    expect(syncState.progress).toBe(100);
    expect(syncState.running).toBe(false);
  });

  it("logs the typed message of a failed run", () => {
    syncState.handleStarted(syncEvent({ total: 1 }));

    syncState.handleFailed(
      syncEvent({
        job: jobMetadata("sync", "failed", { error: { message: "typed sync failed" } }),
        log: logEntry("Error", "Library sync", "typed sync failed"),
      }),
    );

    expect(syncState.status).toBe("failed");
    expect(syncState.log.lines.get(syncState.log.total - 1)).toEqual(
      logEntry("Error", "Library sync", "typed sync failed"),
    );
  });

  it("marks a stopped run without inventing a log line", () => {
    syncState.handleStarted(syncEvent({ total: 2 }));

    syncState.handleStopped(syncEvent({ done: 1, log_targets: { Added: 1 } }));

    expect(syncState.status).toBe("stopped");
    expect(syncState.log.total).toBe(0);
    expect(syncState.count("Added")).toBe(1);
  });

  it("resets every counter", () => {
    syncState.handleProgress(
      syncEvent({ log_targets: { Added: 5, Updated: 5, Unchanged: 5, Removed: 5 } }),
    );

    syncState.reset();

    expect(syncState.count("Added")).toBe(0);
    expect(syncState.status).toBe("idle");
  });
});
