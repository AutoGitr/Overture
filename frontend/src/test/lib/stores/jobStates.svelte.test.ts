import { beforeEach, describe, expect, it } from "vitest";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import { logEntry } from "../../helpers/fixtures";

describe("syncState", () => {
  beforeEach(() => syncState.reset());

  it("handles lifecycle events and completion progress", () => {
    syncState.handleStarted({ total: 2, started_at: "start" });
    const added = logEntry("Added", "Alien", "new library item");
    const removed = logEntry("Removed", "Aliens", "no longer on the media server");
    syncState.handleProgress({ done: 1, added: 1, log: added });
    syncState.handleCompleted({
      done: 2,
      total: 2,
      added: 2,
      unchanged: 0,
      log: removed,
      finished_at: "finish",
    });

    expect(syncState.running).toBe(false);
    expect(syncState.counters.added).toBe(2);
    expect(syncState.done).toBe(2);
    expect(syncState.progress).toBe(100);
    expect(syncState.log).toEqual([added, removed]);
    expect(syncState.finished_at).toBe("finish");
  });

  it("zeroes its own counters on start", () => {
    syncState.handleProgress({ added: 9, updated: 9, unchanged: 9, removed: 9 });

    syncState.handleStarted({ total: 3 });

    expect(syncState.counters).toEqual({ added: 0, updated: 0, unchanged: 0, removed: 0 });
    expect(syncState.total).toBe(3);
  });

  it("keeps counters the first progress event does not carry", () => {
    // The first progress event of a run reports only a log line, so the
    // store must hold the zeros it was just reset to rather than go blank.
    syncState.handleStarted({ total: 3 });
    const started = logEntry("Started", "Sync", "reading libraries from Plex");
    syncState.handleProgress({ log: started });

    expect(syncState.counters.added).toBe(0);
    expect(syncState.counters.unchanged).toBe(0);
    expect(syncState.log).toEqual([started]);
  });

  it("carries the authoritative terminal counts", () => {
    syncState.handleStarted({ total: 4 });
    syncState.handleProgress({ done: 2, added: 2 });

    syncState.handleCompleted({
      done: 4,
      total: 4,
      added: 2,
      updated: 1,
      unchanged: 1,
      removed: 1,
      finished_at: "finish",
    });

    expect(syncState.counters).toEqual({ added: 2, updated: 1, unchanged: 1, removed: 1 });
    expect(syncState.progress).toBe(100);
    expect(syncState.running).toBe(false);
  });

  it("logs the typed message of a failed run", () => {
    syncState.handleStarted({ total: 1 });

    syncState.handleFailed({
      job: {
        kind: "sync",
        status: "failed",
        error: { code: "error", message: "typed sync failed" },
      },
      log: logEntry("Error", "Library sync", "typed sync failed"),
    });

    expect(syncState.status).toBe("failed");
    expect(syncState.log.at(-1)).toEqual(logEntry("Error", "Library sync", "typed sync failed"));
  });

  it("marks a stopped run without inventing a log line", () => {
    syncState.handleStarted({ total: 2 });

    syncState.handleStopped({ done: 1, added: 1 });

    expect(syncState.status).toBe("stopped");
    expect(syncState.log).toEqual([]);
    expect(syncState.counters.added).toBe(1);
  });

  it("resets every counter", () => {
    syncState.handleProgress({ added: 5, updated: 5, unchanged: 5, removed: 5 });

    syncState.reset();

    expect(syncState.counters).toEqual({ added: 0, updated: 0, unchanged: 0, removed: 0 });
    expect(syncState.status).toBe("idle");
  });
});
