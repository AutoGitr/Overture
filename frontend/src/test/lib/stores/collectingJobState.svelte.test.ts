import { describe, expect, it } from "vitest";
import { CollectingJobState } from "../../../lib/stores/collectingJobState.svelte";
import type { JobLogEntry } from "../../../generated/ws";

interface Finding {
  id: number;
  score?: number;
  kind?: string;
  done?: boolean;
}

interface FindingEvent {
  done?: number | null;
  total?: number | null;
  errors?: number | null;
  log?: JobLogEntry | null;
  started_at?: string | null;
  finished_at?: string | null;
  job?: { error?: { message?: string | null } | null } | null;
  findings?: Finding[] | null;
  findings_found?: number | null;
}

function makeState(actionable?: (item: Finding) => boolean) {
  return new CollectingJobState<FindingEvent, Finding>({
    items: (event) => event.findings,
    found: (event) => event.findings_found,
    failureMessage: "Findings job failed",
    groupsOf: (finding) => [[`kind:${finding.kind}`, `Kind ${finding.kind}`]],
    groupOrder: ["kind:b"],
    actionable,
  });
}

/** A state holding *findings*, where finished ones can no longer be acted on. */
function selectionState(findings: Finding[]) {
  const state = makeState((finding) => !finding.done);
  state.handleCompleted({ findings });
  return state;
}

const selectedIds = (state: ReturnType<typeof makeState>) =>
  state.selectedItems.map((item) => item.id);

describe("CollectingJobState", () => {
  it("appends each streamed batch and marks findings selected", () => {
    const state = makeState();

    state.handleStarted({ total: 3 });
    state.handleProgress({ done: 1, findings: [{ id: 1 }], findings_found: 1 });
    state.handleProgress({ done: 2, findings: [{ id: 2 }], findings_found: 2 });

    expect(state.items).toEqual([
      { id: 1, selected: true },
      { id: 2, selected: true },
    ]);
    expect(state.found).toBe(2);
    expect(state.done).toBe(2);
  });

  it("clears previous findings when a new run starts", () => {
    const state = makeState();
    state.handleProgress({ findings: [{ id: 1 }], findings_found: 1 });

    state.handleStarted({ total: 5 });

    expect(state.items).toEqual([]);
    expect(state.found).toBe(0);
    expect(state.total).toBe(5);
  });

  it("replaces the streamed findings with the terminal list", () => {
    const state = makeState();
    state.handleStarted({ total: 2 });
    state.handleProgress({ findings: [{ id: 1 }], findings_found: 1 });

    state.handleCompleted({
      done: 2,
      findings: [{ id: 1 }, { id: 2 }],
      findings_found: 2,
      finished_at: "finish",
    });

    expect(state.items.map((item) => item.id)).toEqual([1, 2]);
    expect(state.running).toBe(false);
    expect(state.finished_at).toBe("finish");
  });

  it("keeps the findings it already has when a terminal event omits them", () => {
    const state = makeState();
    state.handleProgress({ findings: [{ id: 1 }], findings_found: 1 });

    state.handleStopped({ done: 1 });

    expect(state.items.map((item) => item.id)).toEqual([1]);
    expect(state.found).toBe(1);
    expect(state.status).toBe("stopped");
  });

  it("falls back to the collected count when a failure reports none", () => {
    const state = makeState();
    state.handleProgress({ findings: [{ id: 1 }, { id: 2 }], findings_found: 2 });

    state.handleFailed({ job: { error: { message: "boom" } } });

    expect(state.status).toBe("failed");
    expect(state.error).toBe("boom");
    expect(state.found).toBe(2);
  });

  it("uses the configured message when a failure carries none", () => {
    const state = makeState();

    state.handleFailed({});

    expect(state.error).toBe("Findings job failed");
  });

  it("resets back to an idle, empty state", () => {
    const state = makeState();
    state.handleStarted({ total: 2 });
    state.handleProgress({ findings: [{ id: 1 }], findings_found: 1 });

    state.reset();

    expect(state.status).toBe("idle");
    expect(state.items).toEqual([]);
    expect(state.found).toBe(0);
    expect(state.total).toBeNull();
  });
});

describe("CollectingJobState selection", () => {
  it("toggles one finding, or a range from the one toggled last", () => {
    const state = selectionState([1, 2, 3, 4, 5].map((id) => ({ id })));

    state.setSelected(false);
    state.toggle(1);
    state.toggle(3, true);
    expect(selectedIds(state)).toEqual([2, 3, 4]);

    // The range takes the clicked finding's new state, in either direction.
    state.toggle(0, true);
    expect(selectedIds(state)).toEqual([1, 2, 3, 4]);
    state.toggle(2);
    state.toggle(3, true);
    expect(selectedIds(state)).toEqual([1, 2]);
  });

  it("starts a range at the clicked finding when nothing was toggled yet", () => {
    const state = selectionState([{ id: 1 }, { id: 2 }, { id: 3 }]);

    state.toggle(2, true);

    expect(selectedIds(state)).toEqual([1, 2]);
  });

  it("never selects findings that can no longer be acted on", () => {
    const state = selectionState([{ id: 1 }, { id: 2, done: true }, { id: 3 }]);
    expect(state.items.map((item) => item.selected)).toEqual([true, false, true]);

    state.setSelected(false);
    state.toggle(0);
    state.toggle(2, true);
    state.toggle(1);

    expect(state.items.map((item) => item.selected)).toEqual([true, false, true]);
    expect(state.actionableItems.map((item) => item.id)).toEqual([1, 3]);
  });

  it("selects only the findings a predicate accepts", () => {
    const state = selectionState([
      { id: 1, kind: "a" },
      { id: 2, kind: "b" },
      { id: 3, kind: "a" },
    ]);

    state.setSelected(false, (finding) => finding.kind === "b");

    expect(selectedIds(state)).toEqual([1, 3]);
  });

  it("counts every finding per group, listed groups first, then by label", () => {
    const state = selectionState([
      { id: 1, kind: "c" },
      { id: 2, kind: "a", done: true },
      { id: 3, kind: "b" },
      { id: 4, kind: "a" },
    ]);

    expect(state.groups).toEqual([
      { key: "kind:b", label: "Kind b", count: 1, shown: true },
      { key: "kind:a", label: "Kind a", count: 2, shown: true },
      { key: "kind:c", label: "Kind c", count: 1, shown: true },
    ]);
  });

  it("acts only on shown findings and keeps a hidden one's check for later", () => {
    const state = selectionState([
      { id: 1, kind: "a" },
      { id: 2, kind: "b" },
      { id: 3, kind: "a" },
      { id: 4, kind: "b" },
    ]);

    state.toggleGroup("kind:b");

    expect(state.shown.map(({ index }) => index)).toEqual([0, 2]);
    expect(state.hiddenSelectedCount).toBe(2);
    expect(state.groups.find((group) => group.key === "kind:b")?.shown).toBe(false);
    expect(selectedIds(state)).toEqual([1, 3]);
    state.setSelected(false);
    state.toggle(0);
    state.toggle(2, true);
    expect(selectedIds(state)).toEqual([1, 3]);

    state.toggleGroup("kind:b");
    expect(selectedIds(state)).toEqual([1, 2, 3, 4]);
  });

  it("forgets where a range starts when a new page of findings arrives", () => {
    const state = selectionState([{ id: 1 }, { id: 2 }, { id: 3 }]);
    state.toggle(0);

    state.handleCompleted({ findings: [{ id: 4 }, { id: 5 }, { id: 6 }] });
    state.toggle(2, true);

    expect(selectedIds(state)).toEqual([4, 5]);
  });
});
