import { beforeEach, describe, expect, it } from "vitest";
import type { AssetIssue } from "../../../generated/ws";
import { assetManagerState } from "../../../lib/stores/assetManagerState.svelte";

function issue(overrides: Partial<AssetIssue> = {}): AssetIssue {
  return {
    folder: "/media/Movie",
    current_path: "/media/Movie/cover.jpg",
    current_filename: "cover.jpg",
    suggested_path: "/media/Movie/poster.jpg",
    suggested_filename: "poster.jpg",
    potential_false_positive: false,
    type: "poster",
    conflict: false,
    width: 1000,
    height: 1500,
    ...overrides,
  };
}

describe("assetManagerState", () => {
  beforeEach(() => assetManagerState.reset());

  it("streams issues before the scan completes and keeps them", () => {
    assetManagerState.handleStarted({ total: 2 });
    assetManagerState.handleProgress({ done: 1, issues_found: 1, issues: [issue()] });
    const streamed = assetManagerState.items;

    expect(streamed).toEqual([expect.objectContaining({ current_filename: "cover.jpg" })]);
    expect(assetManagerState.found).toBe(1);

    assetManagerState.handleCompleted({ done: 2, total: 2, issues_found: 1 });

    expect(assetManagerState.items).toBe(streamed);
    expect(assetManagerState.items[0]?.selected).toBe(true);
  });

  it("marks completed scan issues as selected and counts errors", () => {
    assetManagerState.handleCompleted({ errors: 1, finished_at: "finish", issues: [issue()] });

    expect(assetManagerState.running).toBe(false);
    expect(assetManagerState.errors).toBe(1);
    expect(assetManagerState.found).toBe(1);
    expect(assetManagerState.items[0]).toMatchObject({
      current_filename: "cover.jpg",
      selected: true,
    });
  });

  it("preselects only free slots suggested by name", () => {
    assetManagerState.handleCompleted({
      issues: [
        issue(),
        issue({ current_filename: "IMG_1.jpg", potential_false_positive: true }),
        issue({ current_filename: "folder.jpg", conflict: true, conflict_with: "cover.jpg" }),
      ],
      issues_found: 3,
    });

    expect(assetManagerState.items.map((found) => found.selected)).toEqual([true, false, false]);
  });

  it("applies same-length terminal snapshot patches", () => {
    assetManagerState.handleCompleted({ issues: [issue()] });
    assetManagerState.handleCompleted({ issues: [issue({ renamed: true })] });

    expect(assetManagerState.items[0]?.renamed).toBe(true);
  });
});
