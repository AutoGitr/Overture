/** State for the Asset Renamer scan job. */
import type { AssetRenameResult } from "../../generated/rest/types.gen";
import type { AssetIssue, AssetScanProgressEvent } from "../../generated/ws";
import { ASSET_LABELS } from "../utils/artTypes";
import { CollectingJobState, type Selectable } from "./collectingJobState.svelte";

export const FALSE_POSITIVE_LABEL = "Possible False Positive";

/** Where an issue stands, the most pressing first. */
const ISSUE_STATUSES = {
  renamed: "Renamed",
  failed: "Rename Failed",
  conflict: "Conflict",
  false_positive: FALSE_POSITIVE_LABEL,
  ready: "Ready",
} as const;

function issueStatus(issue: AssetIssue): keyof typeof ISSUE_STATUSES {
  if (issue.renamed) return "renamed";
  if (issue.rename_error) return "failed";
  if (issue.conflict) return "conflict";
  return issue.potential_false_positive ? "false_positive" : "ready";
}

export type SelectableAssetIssue = Selectable<AssetIssue>;

class AssetManagerState extends CollectingJobState<AssetScanProgressEvent, AssetIssue> {
  constructor() {
    super({
      items: (event) => event.issues,
      found: (event) => event.issues_found,
      groupsOf: (issue) => {
        const status = issueStatus(issue);
        return [
          [`type:${issue.type}`, ASSET_LABELS[issue.type]],
          [`status:${status}`, ISSUE_STATUSES[status]],
        ];
      },
      groupOrder: [
        ...Object.keys(ASSET_LABELS).map((type) => `type:${type}`),
        ...Object.keys(ISSUE_STATUSES).map((status) => `status:${status}`),
      ],
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
