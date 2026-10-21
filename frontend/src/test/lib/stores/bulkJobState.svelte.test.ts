import { describe, expect, it } from "vitest";
import type { BulkArtJobEvent } from "../../../generated/ws";
import { BulkJobState } from "../../../lib/stores/bulkJobState.svelte";
import { logEntry, loggedLines } from "../../helpers/fixtures";

describe("BulkJobState", () => {
  it("resets counters when a bulk job starts", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleProgress({
      done: 3,
      total: 10,
      adopted: 2,
      log: logEntry("Adopted", "Old", "identical"),
    });

    state.handleStarted({ total: 20 });

    expect(state.running).toBe(true);
    expect(state.done).toBe(0);
    expect(state.total).toBe(20);
    expect(state.counters.adopted).toBe(0);
    expect(state.log.total).toBe(0);
  });

  it("accumulates progress logs and computes percentage", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleStarted({ total: 4 });
    const adopted = logEntry("Adopted", "Alien", "identical to the local file");
    const skipped = logEntry("Skipped", "Aliens", "saved selection");
    state.handleProgress({ done: 1, adopted: 1, log: adopted });
    state.handleProgress({ done: 2, skipped: 1, log: skipped });

    expect(state.progress).toBe(50);
    expect(loggedLines(state.log)).toEqual([adopted, skipped]);
  });

  it("moves the bar with every item of a long run", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleStarted({ total: 4450 });
    state.handleProgress({ done: 1 });
    const first = state.progress;
    state.handleProgress({ done: 2 });

    expect(first).toBeGreaterThan(0);
    expect(state.progress).toBeGreaterThan(first);
  });

  it("follows the stored log of the run each event names", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleStarted({ run_id: "run", log_total: 0 });
    state.handleProgress({
      run_id: "run",
      log_total: 1,
      log: logEntry("Queued", "Alien (poster)", "OvertureDB artwork"),
    });

    expect(state.log.total).toBe(1);
    expect(state.log.lines.get(0)?.target).toBe("Alien (poster)");
    expect(state.hasRun).toBe(true);
  });

  it("preserves final counts and marks completion timestamps", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted({ total: 2 });

    state.handleCompleted({
      done: 2,
      adopted: 1,
      no_match: 1,
      finished_at: "2026-05-17T10:00:00Z",
    });

    expect(state.running).toBe(false);
    expect(state.finished_at).toBe("2026-05-17T10:00:00Z");
    expect(state.counters.adopted).toBe(1);
    expect(state.counters.no_match).toBe(1);
  });

  it("restores elapsed timer timestamps from a terminal snapshot", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleCompleted({
      done: 2,
      total: 2,
      started_at: "2026-05-17T09:59:00Z",
      finished_at: "2026-05-17T10:00:00Z",
    });

    expect(state.started_at).toBe("2026-05-17T09:59:00Z");
    expect(state.finished_at).toBe("2026-05-17T10:00:00Z");
  });

  it("acknowledges accepted starts without regressing a delivered lifecycle event", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.markStartAccepted();
    expect(state.running).toBe(true);
    expect(state.status).toBe("running");

    state.handleCompleted({ finished_at: "finish" });
    state.markStartAccepted();
    expect(state.running).toBe(false);
    expect(state.status).toBe("completed");
  });
});

describe("applyCounters", () => {
  it("keeps the current value for any counter the event omits", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted({ total: 4 });
    state.handleProgress({ done: 1, adopted: 2, downloaded: 1, skipped: 1 });

    // A later event that reports only `done` must not zero the rest.
    state.handleProgress({ done: 2 });

    expect(state.counters.adopted).toBe(2);
    expect(state.counters.downloaded).toBe(1);
    expect(state.counters.skipped).toBe(1);
    expect(state.done).toBe(2);
  });

  it("treats an explicit null the same as an omitted counter", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleProgress({ adopted: 3 });

    state.handleProgress({ adopted: null });

    expect(state.counters.adopted).toBe(3);
  });

  it("accepts a zero, which is a real value and not an absent one", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleProgress({ adopted: 3 });

    state.handleProgress({ adopted: 0 });

    expect(state.counters.adopted).toBe(0);
  });

  it("applies counters on every terminal status", () => {
    const completed = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    completed.handleCompleted({ adopted: 1, no_match: 2, skipped: 3, downloaded: 4 });
    expect([
      completed.counters.adopted,
      completed.counters.no_match,
      completed.counters.skipped,
      completed.counters.downloaded,
    ]).toEqual([1, 2, 3, 4]);

    const stopped = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    stopped.handleStopped({ adopted: 5 });
    expect(stopped.counters.adopted).toBe(5);

    const failed = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    failed.handleFailed({ adopted: 6 });
    expect(failed.counters.adopted).toBe(6);
  });
});

describe("downloading", () => {
  it("is on while deciding is over and queued downloads have not all settled", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted({ total: 2 });

    state.handleProgress({ done: 1, queued: 2, settled: 0 });
    expect(state.unsettled).toBe(2);
    expect(state.downloading).toBe(false);

    state.handleProgress({ done: 2, queued: 2, settled: 1 });
    expect(state.unsettled).toBe(1);
    expect(state.downloading).toBe(true);

    // A failed download settles too, so the run is not stuck "downloading".
    state.handleProgress({ done: 2, queued: 2, downloaded: 1, errors: 1, settled: 2 });
    expect(state.unsettled).toBe(0);
    expect(state.downloading).toBe(false);
  });

  it("is off once the run has finished", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted({ total: 1 });
    state.handleCompleted({ done: 1, queued: 1, settled: 0 });

    expect(state.downloading).toBe(false);
  });
});

describe("planning", () => {
  it("has no total until the run has planned its work, then keeps it", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted({});

    expect(state.planning).toBe(true);
    expect(state.total).toBeNull();
    expect(state.progress).toBe(0);
    expect(state.downloading).toBe(false);

    state.handleProgress({ done: 0, total: 5 });
    expect(state.planning).toBe(false);

    state.handleProgress({ done: 2, log: logEntry("Skipped", "Movie", "reason") });
    expect(state.total).toBe(5);
    expect(state.progress).toBe(40);
  });

  it("is off for a run stopped before it finished planning", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted({});
    state.handleStopped({});

    expect(state.planning).toBe(false);
    expect(state.total).toBeNull();
  });
});
