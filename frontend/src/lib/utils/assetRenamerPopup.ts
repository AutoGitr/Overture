import type { SelectableAssetIssue } from "../stores/assetManagerState.svelte";

/** Build the rename request payload for the given selected issues. */
export function assetRenameRequests(issues: SelectableAssetIssue[]) {
  return issues.map((issue) => ({
    current_path: issue.current_path,
    suggested_path: issue.suggested_path,
  }));
}
