import { afterEach, describe, expect, it, vi } from "vitest";
import { JobLogFeed } from "../../../lib/stores/jobLogFeed.svelte";
import { JobLifecycleState } from "../../../lib/stores/jobLifecycleState.svelte";
import { logEntry } from "../../helpers/fixtures";
import { type FetchCall, mockFetchRoutes } from "../../helpers/fetch";
import type { JobOutcome } from "../../../generated/ws";

/** A stored log of `total` lines whose targets name their position. */
function storedLog(total: number) {
  return mockFetchRoutes({
    "/api/job-snapshots/log/run": ({ url }: FetchCall) => {
      const params = new URL(url, location.origin).searchParams;
      const offset = Number(params.get("offset"));
      const limit = Number(params.get("limit"));
      const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) =>
        logEntry("Checked", `Line ${offset + i}`, "stored"),
      );
      return Response.json({ run_id: "run", total, offset, items });
    },
  });
}

/** A stored log of *outcomes*, which the server filters by the outcomes asked for. */
function storedOutcomes(outcomes: JobOutcome[]) {
  return mockFetchRoutes({
    "/api/job-snapshots/log/run": ({ url }: FetchCall) => {
      const params = new URL(url, location.origin).searchParams;
      const offset = Number(params.get("offset"));
      const asked = params.getAll("outcome");
      const lines = outcomes
        .map((outcome, ordinal) => logEntry(outcome, `Line ${ordinal}`, "stored"))
        .filter((entry) => !asked.length || asked.includes(entry.outcome));
      return Response.json({
        run_id: "run",
        total: lines.length,
        offset,
        items: lines.slice(offset, offset + 200),
      });
    },
  });
}

describe("JobLogFeed", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("places each live line where the run numbered it", () => {
    const feed = new JobLogFeed();

    feed.apply({ run_id: "run", log_total: 0 });
    feed.apply({ run_id: "run", log_total: 1, log: logEntry("Added", "Alien", "new") });
    feed.apply({ run_id: "run", log_total: 5, log: logEntry("Added", "Aliens", "new") });

    expect(feed.total).toBe(5);
    expect(feed.lines.get(0)?.target).toBe("Alien");
    expect(feed.lines.get(4)?.target).toBe("Aliens");
    expect(feed.lines.has(2)).toBe(false);
  });

  it("starts over when a new run begins", () => {
    const feed = new JobLogFeed();
    feed.apply({ run_id: "old", log_total: 1, log: logEntry("Added", "Alien", "new") });

    feed.apply({ run_id: "new", log_total: 0 });

    expect(feed.total).toBe(0);
    expect(feed.lines.size).toBe(0);
  });

  it("numbers the lines of a run that is not stored itself", () => {
    const feed = new JobLogFeed();

    feed.apply({ log: logEntry("Started", "Backup", "running") });
    feed.apply({ log: logEntry("Added", "Backup", "done") });

    expect(feed.total).toBe(2);
    expect(feed.lines.get(1)?.reason).toBe("done");
  });

  it("fetches the stored lines that scroll into view", async () => {
    const { calls } = storedLog(500);
    const feed = new JobLogFeed();
    feed.apply({ run_id: "run", log_total: 500 });

    feed.show(190, 210);

    await vi.waitFor(() => expect(feed.lines.get(209)?.target).toBe("Line 209"));
    expect(calls.map((call) => call.url)).toEqual([
      "/api/job-snapshots/log/run?offset=0&limit=200",
      "/api/job-snapshots/log/run?offset=200&limit=200",
    ]);

    feed.show(195, 205);
    expect(calls).toHaveLength(2);
  });

  it("drops lines far from the view and fetches them again when needed", async () => {
    storedLog(5000);
    const feed = new JobLogFeed();
    feed.apply({ run_id: "run", log_total: 5000 });
    feed.show(0, 20);
    await vi.waitFor(() => expect(feed.lines.has(0)).toBe(true));

    feed.show(4000, 4020);

    expect(feed.lines.has(0)).toBe(false);
    await vi.waitFor(() => expect(feed.lines.get(4000)?.target).toBe("Line 4000"));
  });

  it("lists only the outcomes shown, by the counts the run's events carry", async () => {
    storedOutcomes(["Added", "Error", "Added", "Unchanged"]);
    const feed = new JobLogFeed();
    feed.apply({
      run_id: "run",
      log_total: 4,
      log_outcomes: { Added: 2, Error: 1, Unchanged: 1 },
    });
    feed.show(0, 4);
    await vi.waitFor(() => expect(feed.lines.size).toBe(4));
    expect(feed.groups.map(({ key, count, shown }) => [key, count, shown])).toEqual([
      ["Added", 2, true],
      ["Unchanged", 1, true],
      ["Error", 1, true],
    ]);

    feed.toggleOutcome("Added");

    expect(feed.groups.find((group) => group.key === "Added")?.shown).toBe(false);
    expect(feed.total).toBe(2);
    await vi.waitFor(() => expect(feed.lines.get(1)?.target).toBe("Line 3"));
    expect(feed.lines.get(0)?.target).toBe("Line 1");

    // A live line joins the filtered list only when its outcome is shown.
    feed.apply({
      run_id: "run",
      log_total: 5,
      log_outcomes: { Added: 3, Error: 1, Unchanged: 1 },
      log: logEntry("Added", "Line 4", "live"),
    });
    feed.apply({
      run_id: "run",
      log_total: 6,
      log_outcomes: { Added: 3, Error: 2, Unchanged: 1 },
      log: logEntry("Error", "Line 5", "live"),
    });
    expect([feed.total, feed.lines.get(2)?.target]).toEqual([3, "Line 5"]);
  });

  it("offers a retry when a page fails to load", async () => {
    mockFetchRoutes({});
    const feed = new JobLogFeed();
    feed.apply({ run_id: "run", log_total: 10 });

    feed.show(0, 10);
    await vi.waitFor(() => expect(feed.error).not.toBe(""));

    storedLog(10);
    feed.retry();
    await vi.waitFor(() => expect(feed.lines.size).toBe(10));
    expect(feed.error).toBe("");
  });

  it("fills an incomplete visible page when the operation stops without scrolling", async () => {
    const job = new JobLifecycleState({ failureMessage: "Failed" });
    const { calls } = storedLog(0);
    job.handleStarted({ run_id: "run", log_total: 3 });
    job.log.show(0, 3);
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    storedLog(3);
    job.handleStopped({ run_id: "run", log_total: 3 });
    await vi.waitFor(() => expect(job.log.lines.size).toBe(3));
    expect(job.log.lines.get(2)?.target).toBe("Line 2");
  });
});
