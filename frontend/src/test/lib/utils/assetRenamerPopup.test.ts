import { describe, expect, it } from "vitest";
import type { SelectableAssetIssue } from "../../../lib/stores/assetManagerState.svelte";
import { assetRenameRequests } from "../../../lib/utils/assetRenamerPopup";

function issue(overrides: Partial<SelectableAssetIssue> = {}): SelectableAssetIssue {
  return {
    current_path: "/movies/a.jpg",
    suggested_path: "/movies/poster.jpg",
    current_filename: "a.jpg",
    suggested_filename: "poster.jpg",
    folder: "/movies",
    type: "poster",
    selected: true,
    renamed: false,
    conflict: false,
    ...overrides,
  } as SelectableAssetIssue;
}

describe("assetRenameRequests", () => {
  it("maps issues to current/suggested path pairs", () => {
    expect(assetRenameRequests([issue()])).toEqual([
      { current_path: "/movies/a.jpg", suggested_path: "/movies/poster.jpg" },
    ]);
  });
});
