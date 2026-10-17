import { afterEach, describe, expect, it, vi } from "vitest";
import { JobResultPage } from "../../../lib/stores/jobResultPage.svelte";
import { CollectingJobState } from "../../../lib/stores/collectingJobState.svelte";
import type { JobLogEntry } from "../../../generated/ws";
import { logEntry } from "../../helpers/fixtures";
import { getDownloadBacklog, getJobResults } from "../../../generated/rest/sdk.gen";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import type { DownloadJobEvent } from "../../../generated/ws";

vi.mock(import("../../../generated/rest/sdk.gen"), async (importOriginal) => ({
  ...(await importOriginal()),
  getDownloadBacklog: vi.fn(),
  getJobResults: vi.fn(),
}));

type Answer = { data: unknown };
// The SDK resolves to the parsed body; only `data` matters to these stores.
const fetchPage = vi.mocked(getJobResults) as unknown as ReturnType<
  typeof vi.fn<(options: { query?: { offset?: number; limit?: number } }) => Promise<Answer>>
>;
const fetchBacklog = vi.mocked(getDownloadBacklog) as unknown as ReturnType<
  typeof vi.fn<(options: { query?: { after?: string | null } }) => Promise<Answer>>
>;
const response = (run: string, offset: number, ids: number[]): Answer => ({
  data: { run_id: run, total: 205, offset, items: ids.map((id) => ({ id })) },
});
const backlog = (items: DownloadJobEvent[], next_cursor: string | null): Answer => ({
  data: { items, next_cursor },
});

afterEach(() => {
  downloadState.replaceSnapshot([]);
  vi.resetAllMocks();
});

function download(id: string, percent = 0): DownloadJobEvent {
  return {
    percent,
    stage: "queued",
    unchanged: null,
    job: {
      id,
      kind: "download",
      status: "pending",
      error: null,
      target: {
        target_type: "item",
        media_item_id: 1,
        title: "Alien",
        job_type: "art",
        art_type: "poster",
        season_id: null,
      },
    },
  };
}

describe("job result pagination", () => {
  it("pages pending downloads without overwriting live progress or resurrecting completed jobs", async () => {
    let resolvePage: (value: Answer) => void = () => {};
    fetchBacklog.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePage = resolve;
        }),
    );
    fetchBacklog.mockResolvedValueOnce(backlog([download("third")], null));
    downloadState.replaceSnapshot([], true);
    downloadState.handleFinished(download("done"));
    downloadState.handleProgress(download("active", 80));
    resolvePage(backlog([download("done"), download("active", 10)], "active"));
    await vi.waitFor(() => expect(downloadState.loadingPending).toBe(false));
    expect(downloadState.activeCount).toBe(2);
    expect(downloadState.getJobsForItem(1).find((job) => job.job_id === "active")?.percent).toBe(
      80,
    );
    expect(fetchBacklog.mock.lastCall?.[0].query?.after).toBe("active");
  });

  it("ignores a pending download page from the previous snapshot", async () => {
    let resolvePage: (value: Answer) => void = () => {};
    fetchBacklog.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePage = resolve;
        }),
    );
    downloadState.replaceSnapshot([], true);
    downloadState.replaceSnapshot([download("new")]);
    resolvePage(backlog([download("old")], null));
    await Promise.resolve();
    await Promise.resolve();
    expect(downloadState.getJobsForItem(1).map((job) => job.job_id)).toEqual(["new"]);
  });
  it("replaces the current page and preserves its position when a snapshot is refreshed", async () => {
    let items: { id: number }[] = [];
    const page = new JobResultPage<{ id: number }>((rows) => {
      items = rows;
    });
    fetchPage.mockResolvedValueOnce(response("run", 0, [1]));
    page.update({ results_run_id: "run", results_total: 205 }, true);
    await vi.waitFor(() => expect(page.loading).toBe(false));
    fetchPage.mockResolvedValueOnce(response("run", 100, [101]));
    await page.load(100);
    expect(items).toEqual([{ id: 101 }]);
    expect(page.offset).toBe(100);
    fetchPage.mockResolvedValueOnce(response("run", 100, [102]));
    page.update({ results_run_id: "run" }, true);
    await vi.waitFor(() => expect(items).toEqual([{ id: 102 }]));
    expect(fetchPage.mock.lastCall?.[0].query).toEqual({ offset: 100, limit: 100 });
  });

  it("discards a late page after a new run or reset even if the transport ignores abort", async () => {
    let resolveOld: (value: Answer) => void = () => {};
    let items: { id: number }[] = [];
    const page = new JobResultPage<{ id: number }>((rows) => {
      items = rows;
    });
    fetchPage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    page.update({ results_run_id: "old" });
    fetchPage.mockResolvedValueOnce(response("new", 0, [2]));
    page.update({ results_run_id: "new" });
    await vi.waitFor(() => expect(items).toEqual([{ id: 2 }]));
    resolveOld(response("old", 0, [1]));
    await Promise.resolve();
    expect(items).toEqual([{ id: 2 }]);
    fetchPage.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    const loading = page.load();
    page.reset();
    items = [];
    resolveOld(response("new", 0, [3]));
    await loading;
    expect(items).toEqual([]);
    expect(page.loading).toBe(false);
  });

  it("retains the current page on failure and retries without losing the total", async () => {
    const apply = vi.fn();
    const page = new JobResultPage<{ id: number }>(apply);
    fetchPage.mockRejectedValueOnce(new Error("Connection lost"));
    page.update({ results_run_id: "run", results_total: 205 }, true);
    await vi.waitFor(() => expect(page.error).toBe("Connection lost"));
    expect(page.total).toBe(205);
    fetchPage.mockResolvedValueOnce(response("run", 0, [1]));
    await page.load();
    expect(page.error).toBe("");
    expect(apply).toHaveBeenLastCalledWith([{ id: 1 }]);
  });

  it("bounds streamed rows and log history while retaining cumulative counters", () => {
    const state = new CollectingJobState<
      {
        findings?: { id: number }[];
        count?: number;
        log?: JobLogEntry;
        done?: number;
      },
      { id: number }
    >({ itemsKey: "findings", foundKey: "count", failureMessage: "Failed" });
    for (let id = 1; id <= 1000; id++) {
      state.handleProgress({
        findings: [{ id }],
        count: id,
        log: logEntry("Checked", `Row ${id}`, "checked"),
        done: id,
      });
    }
    expect(state.items).toHaveLength(100);
    expect(state.items[0]?.id).toBe(901);
    expect(state.log).toHaveLength(200);
    expect(state.found).toBe(1000);
    state.handleFailed({});
    expect(state.found).toBe(1000);
  });
});
