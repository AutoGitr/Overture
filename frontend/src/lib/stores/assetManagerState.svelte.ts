/** State for the Asset Renamer scan job. */
import type { AssetRenameResult } from "../../generated/rest/types.gen";
import type { AssetIssue, AssetScanProgressEvent } from "../../generated/ws";
import { CollectingJobState, type Selectable } from "./collectingJobState.svelte";

export type SelectableAssetIssue = Selectable<AssetIssue>;

class AssetManagerState extends CollectingJobState<AssetScanProgressEvent, AssetIssue> {
  constructor() {
    super({
      itemsKey: "issues",
      foundKey: "issues_found",
      failureMessage: "Asset scan failed",
      // Only a suggestion named for its slot, with the slot free, is renamed
      // without a second look.
      preselect: (issue) => !issue.potential_false_positive,
      actionable: (issue) => !issue.renamed && !issue.conflict,
    });
  }

  /** Show what a rename did to each issue it was asked to fix. */
  applyRenameResults(results: AssetRenameResult[]) {
    const byPath = new Map(results.map((result) => [result.current_path, result]));
    this.items = this.items.map((issue) => {
      const result = byPath.get(issue.current_path);
      if (!result) return issue;
      if (result.status === "renamed") return { ...issue, renamed: true, rename_error: null };
      if (result.status === "conflict") return { ...issue, conflict: true };
      return { ...issue, rename_error: result.reason ?? "Rename failed" };
    });
  }
}

export const assetManagerState = new AssetManagerState();
