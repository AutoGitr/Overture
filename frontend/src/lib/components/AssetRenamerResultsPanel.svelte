<script lang="ts">
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import JobCount from "./JobCount.svelte";
  import JobElapsedTime from "./JobElapsedTime.svelte";
  import JobResults from "./JobResults.svelte";
  import JobResultsList from "./JobResultsList.svelte";
  import JobResultPagination from "./JobResultPagination.svelte";
  import type { AssetIssue } from "../../generated/ws";
  import { assetManagerState } from "../stores/assetManagerState.svelte";
  import type { SelectionGroupsOf } from "../stores/collectingJobState.svelte";
  import { ASSET_BADGES, ASSET_LABELS } from "../utils/artTypes";

  const FALSE_POSITIVE_LABEL = "Possible False Positive";

  /** Art types in their usual order, then the flag to double-check. */
  const GROUP_ORDER = [
    ...Object.keys(ASSET_LABELS).map((type) => `type:${type}`),
    "false_positive",
  ];

  const groupsOf: SelectionGroupsOf<AssetIssue> = (issue) => [
    [`type:${issue.type}`, ASSET_LABELS[issue.type]],
    ...(issue.potential_false_positive ? [["false_positive", FALSE_POSITIVE_LABEL] as const] : []),
  ];

  let selectedCount = $derived(assetManagerState.selectedItems.length);
</script>

<JobResults progress={assetManagerState.progress} log={assetManagerState.log}>
  {#snippet stats()}
    <div class="stats-row">
      <JobCount job={assetManagerState} unit="folders" />
      <div class="stat-item" title="Files with a suggested new name">
        issues: <span class="stat-value">{assetManagerState.found}</span>
      </div>
      <div class="stat-item">
        errors: <span class="stat-value text-danger">{assetManagerState.errors}</span>
      </div>
      <JobElapsedTime
        startedAt={assetManagerState.started_at}
        finishedAt={assetManagerState.finished_at}
      />
    </div>
  {/snippet}

  <JobResultsList
    itemCount={assetManagerState.items.length}
    itemSize={72}
    heading="{assetManagerState.items.length} issues on this page"
    subtitle={assetManagerState.running
      ? "Results update live while scanning"
      : `${selectedCount} selected on this page for rename`}
    emptyLabel="All assets are correctly named!"
    showEmpty={Boolean(assetManagerState.finished_at)}
    {selectedCount}
    actionableCount={assetManagerState.actionableItems.length}
    groups={assetManagerState.selectionGroups(groupsOf, GROUP_ORDER)}
    running={assetManagerState.running}
    onSelectAll={(checked) => assetManagerState.setSelected(checked)}
    onToggleGroup={(key) => assetManagerState.toggleGroup(groupsOf, key)}
  >
    {#snippet row(idx: number, style: string)}
      {@const issue = assetManagerState.items[idx]}
      {#if issue}
        <label
          class="issue-item"
          class:issue-dimmed={issue.renamed}
          class:issue-flagged={issue.conflict}
          {style}
        >
          <span class="issue-checkbox">
            <input
              type="checkbox"
              checked={issue.selected && assetManagerState.isActionable(issue)}
              disabled={assetManagerState.running || !assetManagerState.isActionable(issue)}
              onclick={(event) => assetManagerState.toggle(idx, event.shiftKey)}
            />
          </span>
          <span class="issue-details">
            <span class="issue-filenames">
              <span class="issue-current truncate" title={issue.current_path}
                >{issue.current_filename}</span
              >
              <span class="issue-arrow">-&gt;</span>
              <span class="issue-suggested truncate" title={issue.suggested_path}
                >{issue.suggested_filename}</span
              >
            </span>
            <span class="issue-meta">
              <span class="badge {ASSET_BADGES[issue.type]}">{ASSET_LABELS[issue.type]}</span>
              {#if issue.potential_false_positive}
                <span
                  class="badge badge-warning"
                  title="Only the file's shape suggests this type; its name does not. Check it before renaming."
                  >Warning: {FALSE_POSITIVE_LABEL}</span
                >
              {/if}
              {#if issue.width && issue.height}
                <span class="badge badge-muted">{issue.width}x{issue.height}</span>
              {/if}
              <span class="issue-folder truncate" title={issue.folder}
                >{issue.folder.split("/").slice(-2).join("/")}</span
              >
            </span>
          </span>
          <span class="issue-status">
            {#if issue.renamed}
              <span class="status-ok" title="Renamed successfully">OK</span>
            {:else if issue.conflict}
              <span
                class="status-warn"
                title={issue.conflict_with
                  ? `${issue.conflict_with} already fills this slot or is suggested for it`
                  : "Another file already fills this slot"}
              >
                <TriangleAlert size={14} />
              </span>
            {:else if issue.rename_error}
              <span class="status-err" title={issue.rename_error}>Error</span>
            {/if}
          </span>
        </label>
      {/if}
    {/snippet}
  </JobResultsList>
  <JobResultPagination page={assetManagerState.page} running={assetManagerState.running} />
</JobResults>
