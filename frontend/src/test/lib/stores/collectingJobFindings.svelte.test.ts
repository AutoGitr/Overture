import { afterEach, describe, expect, it, vi } from "vitest";
import { CollectingJobState } from "../../../lib/stores/collectingJobState.svelte";
import { logEntry } from "../../helpers/fixtures";

type Answer = { data: unknown };
// Only `data` of the SDK's answer matters to this store.
const { fetchResults } = vi.hoisted(() => ({
  fetchResults: vi.fn<(options: { path: { run_id: string } }) => Promise<Answer>>(),
}));
vi.mock("../../../generated/rest/sdk.gen", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../generated/rest/sdk.gen")>()),
  getJobResults: fetchResults,
}));

interface Finding {
  id: number;
}

interface FindingEvent {
  run_id?: string | null;
  results_total?: number | null;
  findings?: Finding[] | null;
  findings_found?: number | null;
}

const stored = (run: string, ids: number[]): Answer => ({
  data: { run_id: run, items: ids.map((id) => ({ id })) },
});
const range = (from: number, to: number) => Array.from({ length: to - from }, (_, i) => from + i);
const ids = (state: CollectingJobState<FindingEvent, Finding>) =>
  state.items.map((item) => item.id);

function makeState() {
  return new CollectingJobState<FindingEvent, Finding>({
    items: (event) => event.findings,
    found: (event) => event.findings_found,
    failureMessage: "Findings job failed",
    groupsOf: () => [],
    groupOrder: [],
  });
}

afterEach(() => {
  vi.resetAllMocks();
});

describe("a collecting job's findings", () => {
  it("keeps every streamed finding of a run without fetching any", () => {
    const state = makeState();
    state.handleStarted({ run_id: "run", results_total: 0 });

    for (let id = 0; id < 1000; id++) {
      state.handleProgress({ run_id: "run", results_total: id + 1, findings: [{ id }] });
    }

    expect(ids(state)).toEqual(range(0, 1000));
    expect(fetchResults).not.toHaveBeenCalled();
  });

  it("fetches the whole run when a batch does not follow on from the findings held", async () => {
    fetchResults.mockResolvedValueOnce(stored("run", range(0, 50)));
    const state = makeState();

    // Joining a run part way, after a reconnect.
    state.handleProgress({ run_id: "run", results_total: 50, findings: [{ id: 49 }] });

    await vi.waitFor(() => expect(ids(state)).toEqual(range(0, 50)));
    expect(fetchResults).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ path: { run_id: "run" } }),
    );
    state.handleProgress({ run_id: "run", results_total: 51, findings: [{ id: 50 }] });
    expect(ids(state)).toEqual(range(0, 51));
    expect(fetchResults).toHaveBeenCalledOnce();
  });

  it("fetches again while findings were stored during a fetch", async () => {
    let answer: (value: Answer) => void = () => {};
    fetchResults.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    fetchResults.mockResolvedValueOnce(stored("run", range(0, 3)));
    const state = makeState();
    state.handleStarted({ run_id: "run" });
    state.handleProgress({ run_id: "run", results_total: 2, findings: [{ id: 1 }] });
    // A batch while the fetch is answered waits for it.
    state.handleProgress({ run_id: "run", results_total: 3, findings: [{ id: 2 }] });

    answer(stored("run", range(0, 2)));

    await vi.waitFor(() => expect(ids(state)).toEqual(range(0, 3)));
    expect(fetchResults).toHaveBeenCalledTimes(2);
  });

  it("replaces the findings with the stored ones once the run ends", async () => {
    fetchResults.mockResolvedValueOnce(stored("run", [7, 8]));
    const state = makeState();
    state.handleStarted({ run_id: "run" });
    state.handleProgress({ run_id: "run", results_total: 1, findings: [{ id: 7 }] });

    state.handleCompleted({ run_id: "run", results_total: 2, findings_found: 2 });

    await vi.waitFor(() => expect(ids(state)).toEqual([7, 8]));
    expect(state.items.every((item) => item.selected)).toBe(true);
    expect(state.found).toBe(2);
  });

  it("takes the findings an unstored run reports on its terminal event", () => {
    const state = makeState();

    state.handleCompleted({ findings: [{ id: 1 }, { id: 2 }] });

    expect(ids(state)).toEqual([1, 2]);
    expect(fetchResults).not.toHaveBeenCalled();
  });

  it("drops a late answer for a run that was replaced", async () => {
    let answerOld: (value: Answer) => void = () => {};
    fetchResults.mockImplementationOnce(() => new Promise((resolve) => (answerOld = resolve)));
    const state = makeState();
    state.handleCompleted({ run_id: "old", results_total: 1 });

    state.handleStarted({ run_id: "new", results_total: 0 });
    state.handleProgress({ run_id: "new", results_total: 1, findings: [{ id: 2 }] });
    answerOld(stored("old", [1]));
    await Promise.resolve();
    await Promise.resolve();

    expect(ids(state)).toEqual([2]);
    expect(state.loading).toBe(false);
  });

  it("offers a retry when the stored findings fail to load", async () => {
    fetchResults.mockRejectedValueOnce(new Error("Connection lost"));
    const state = makeState();
    state.handleCompleted({ run_id: "run", results_total: 1 });
    await vi.waitFor(() => expect(state.loadError).toBe("Connection lost"));

    fetchResults.mockResolvedValueOnce(stored("run", [1]));
    state.retry();

    await vi.waitFor(() => expect(ids(state)).toEqual([1]));
    expect(state.loadError).toBe("");
  });

  it("keeps cumulative counters and the whole log beside its findings", () => {
    const state = new CollectingJobState<
      FindingEvent & { log?: ReturnType<typeof logEntry>; done?: number },
      Finding
    >({
      items: (event) => event.findings,
      found: (event) => event.findings_found,
      failureMessage: "Failed",
      groupsOf: () => [],
      groupOrder: [],
    });
    for (let id = 1; id <= 300; id++) {
      state.handleProgress({
        findings: [{ id }],
        findings_found: id,
        log: logEntry("Checked", `Row ${id}`, "checked"),
        done: id,
      });
    }
    expect(state.items).toHaveLength(300);
    expect(state.log.total).toBe(300);
    state.handleFailed({});
    expect(state.found).toBe(300);
  });
});
