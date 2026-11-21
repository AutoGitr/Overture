import { describe, expect, it } from "vitest";
import type { BulkArtJobEvent } from "../../../generated/ws";
import { BulkJobState } from "../../../lib/stores/bulkJobState.svelte";
import { bulkArtEvent, logEntry, loggedLines } from "../../helpers/fixtures";

describe("BulkJobState", () => {
  it("resets counters when a bulk job starts", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleProgress(
      bulkArtEvent({
        done: 3,
        total: 10,
        log: logEntry("Adopted", "Old", "identical"),
        log_targets: { Adopted: 2 },
      }),
    );

    state.handleStarted(bulkArtEvent({ total: 20 }));

    expect(state.running).toBe(true);
    expect(state.done).toBe(0);
    expect(state.total).toBe(20);
    expect(state.count("Adopted")).toBe(0);
    expect(state.log.total).toBe(0);
  });

  it("accumulates progress logs and computes percentage", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleStarted(bulkArtEvent({ total: 4 }));
    const adopted = logEntry("Adopted", "Alien", "identical to the local file");
    const skipped = logEntry("Skipped", "Aliens", "saved selection");
    state.handleProgress(bulkArtEvent({ done: 1, log: adopted, log_targets: { Adopted: 1 } }));
    // Each event carries the run's totals so far.
    state.handleProgress(
      bulkArtEvent({ done: 2, log: skipped, log_targets: { Adopted: 1, Skipped: 1 } }),
    );

    expect(state.progress).toBe(50);
    expect([state.count("Adopted"), state.count("Skipped")]).toEqual([1, 1]);
    expect(loggedLines(state.log)).toEqual([adopted, skipped]);
  });

  it("moves the bar with every item of a long run", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleStarted(bulkArtEvent({ total: 4450 }));
    state.handleProgress(bulkArtEvent({ done: 1 }));
    const first = state.progress;
    state.handleProgress(bulkArtEvent({ done: 2 }));

    expect(first).toBeGreaterThan(0);
    expect(state.progress).toBeGreaterThan(first);
  });

  it("follows the stored log of the run each event names", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleStarted(bulkArtEvent({ run_id: "run", log_total: 0 }));
    state.handleProgress(
      bulkArtEvent({
        run_id: "run",
        log_total: 1,
        log: logEntry("Queued", "Alien (poster)", "OvertureDB artwork"),
      }),
    );

    expect(state.log.total).toBe(1);
    expect(state.log.lines.get(0)?.target).toBe("Alien (poster)");
    expect(state.hasRun).toBe(true);
  });

  it("preserves final counts and marks completion timestamps", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted(bulkArtEvent({ total: 2 }));

    state.handleCompleted(
      bulkArtEvent({
        done: 2,
        finished_at: "2026-05-17T10:00:00Z",
        log_targets: { Adopted: 1, "No match": 1 },
      }),
    );

    expect(state.running).toBe(false);
    expect(state.finished_at).toBe("2026-05-17T10:00:00Z");
    expect(state.count("Adopted")).toBe(1);
    expect(state.count("No match")).toBe(1);
  });

  it("restores elapsed timer timestamps from a terminal snapshot", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.handleCompleted(
      bulkArtEvent({
        done: 2,
        total: 2,
        started_at: "2026-05-17T09:59:00Z",
        finished_at: "2026-05-17T10:00:00Z",
      }),
    );

    expect(state.started_at).toBe("2026-05-17T09:59:00Z");
    expect(state.finished_at).toBe("2026-05-17T10:00:00Z");
  });

  it("acknowledges accepted starts without regressing a delivered lifecycle event", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");

    state.markStartAccepted();
    expect(state.running).toBe(true);
    expect(state.status).toBe("running");

    state.handleCompleted(bulkArtEvent({ finished_at: "finish" }));
    state.markStartAccepted();
    expect(state.running).toBe(false);
    expect(state.status).toBe("completed");
  });
});

describe("log target counts", () => {
  it("keeps the current value for any counter the event omits", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted(bulkArtEvent({ total: 4 }));
    state.handleProgress(
      bulkArtEvent({ done: 1, log_targets: { Adopted: 2, Downloaded: 1, Skipped: 1 } }),
    );

    // A later event that reports only `done` must not zero the rest.
    state.handleProgress(bulkArtEvent({ done: 2 }));

    expect(state.count("Adopted")).toBe(2);
    expect(state.count("Downloaded")).toBe(1);
    expect(state.count("Skipped")).toBe(1);
    expect(state.done).toBe(2);
  });

  it("keeps its counts through an event that carries none", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleProgress(bulkArtEvent({ log_targets: { Adopted: 3 } }));

    state.handleProgress(bulkArtEvent({ log_targets: null }));

    expect(state.count("Adopted")).toBe(3);
  });

  it("accepts a zero, which is a real value and not an absent one", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleProgress(bulkArtEvent({ log_targets: { Adopted: 3 } }));

    state.handleProgress(bulkArtEvent({ log_targets: { Adopted: 0 } }));

    expect(state.count("Adopted")).toBe(0);
  });

  it("applies counters on every terminal status", () => {
    const completed = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    completed.handleCompleted(
      bulkArtEvent({ log_targets: { Adopted: 1, "No match": 2, Skipped: 3, Downloaded: 4 } }),
    );
    expect([
      completed.count("Adopted"),
      completed.count("No match"),
      completed.count("Skipped"),
      completed.count("Downloaded"),
    ]).toEqual([1, 2, 3, 4]);

    const stopped = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    stopped.handleStopped(bulkArtEvent({ log_targets: { Adopted: 5 } }));
    expect(stopped.count("Adopted")).toBe(5);

    const failed = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    failed.handleFailed(bulkArtEvent({ log_targets: { Adopted: 6 } }));
    expect(failed.count("Adopted")).toBe(6);
  });
});

describe("downloading", () => {
  it("is on while deciding is over and queued downloads have not all settled", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted(bulkArtEvent({ total: 2 }));

    state.handleProgress(bulkArtEvent({ done: 1, settled: 0, log_targets: { Queued: 2 } }));
    expect(state.unsettled).toBe(2);
    expect(state.downloading).toBe(false);

    state.handleProgress(bulkArtEvent({ done: 2, settled: 1, log_targets: { Queued: 2 } }));
    expect(state.unsettled).toBe(1);
    expect(state.downloading).toBe(true);

    // A failed download settles too, so the run is not stuck "downloading".
    state.handleProgress(
      bulkArtEvent({ done: 2, settled: 2, log_targets: { Queued: 2, Downloaded: 1, Error: 1 } }),
    );
    expect(state.unsettled).toBe(0);
    expect(state.downloading).toBe(false);
  });

  it("is off once the run has finished", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted(bulkArtEvent({ total: 1 }));
    state.handleCompleted(bulkArtEvent({ done: 1, settled: 0, log_targets: { Queued: 1 } }));

    expect(state.downloading).toBe(false);
  });
});

describe("planning", () => {
  it("has no total until the run has planned its work, then keeps it", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted(bulkArtEvent({}));

    expect(state.planning).toBe(true);
    expect(state.total).toBeNull();
    expect(state.progress).toBe(0);
    expect(state.downloading).toBe(false);

    state.handleProgress(bulkArtEvent({ done: 0, total: 5 }));
    expect(state.planning).toBe(false);

    state.handleProgress(bulkArtEvent({ done: 2, log: logEntry("Skipped", "Movie", "reason") }));
    expect(state.total).toBe(5);
    expect(state.progress).toBe(40);
  });

  it("is off for a run stopped before it finished planning", () => {
    const state = new BulkJobState<BulkArtJobEvent>("Art matching failed");
    state.handleStarted(bulkArtEvent({}));
    state.handleStopped(bulkArtEvent({}));

    expect(state.planning).toBe(false);
    expect(state.total).toBeNull();
  });
});
