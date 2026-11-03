<script lang="ts">
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import IssueRow from "./IssueRow.svelte";
  import JobPanel from "./JobPanel.svelte";
  import JobResultsList from "./JobResultsList.svelte";
  import { assetManagerState, FALSE_POSITIVE_LABEL } from "../stores/assetManagerState.svelte";
  import { ASSET_BADGES, ASSET_LABELS } from "../utils/artTypes";

  let selectedCount = $derived(assetManagerState.selectedItems.length);
</script>

<JobPanel
  job={assetManagerState}
  unit="folders"
  stats={[
    { label: "issues", value: assetManagerState.found, title: "Files with a suggested new name" },
    { label: "errors", value: assetManagerState.errors, tone: "danger" },
  ]}
>
  <JobResultsList
    itemCount={assetManagerState.shown.length}
    total={assetManagerState.items.length}
    itemSize={72}
    noun="issues"
    subtitle="{selectedCount} selected for rename"
    emptyLabel="All assets are correctly named!"
    showEmpty={Boolean(assetManagerState.finished_at)}
    {selectedCount}
    hiddenSelectedCount={assetManagerState.hiddenSelectedCount}
    actionableCount={assetManagerState.actionableItems.length}
    groups={assetManagerState.groups}
    running={assetManagerState.running}
    findings={assetManagerState}
    onSelectAll={(checked) => assetManagerState.setSelected(checked)}
    onToggleGroup={(key) => assetManagerState.toggleGroup(key)}
  >
    {#snippet row(idx: number, style: string)}
      {@const shown = assetManagerState.shown[idx]}
      {#if shown}
        {@const { index, item: issue } = shown}
        <IssueRow
          {style}
          checked={issue.selected && assetManagerState.isActionable(issue)}
          disabled={assetManagerState.running || !assetManagerState.isActionable(issue)}
          dimmed={issue.renamed}
          flagged={issue.conflict}
          ontoggle={(range) => assetManagerState.toggle(index, range)}
        >
          {#snippet title()}
            <span class="issue-name truncate" title={issue.current_path}
              >{issue.current_filename}</span
            >
            <span class="arrow">-&gt;</span>
            <span class="suggested truncate" title={issue.suggested_path}
              >{issue.suggested_filename}</span
            >
          {/snippet}
          {#snippet meta()}
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
          {/snippet}
          {#snippet status()}
            {#if issue.renamed}
              <span class="status-ok" title="Renamed successfully">OK</span>
            {:else if issue.conflict}
              <span
                class="conflict"
                title={issue.conflict_with
                  ? `${issue.conflict_with} already fills this slot or is suggested for it`
                  : "Another file already fills this slot"}
              >
                <TriangleAlert size={14} />
              </span>
            {:else if issue.rename_error}
              <span class="status-err" title={issue.rename_error}>Error</span>
            {/if}
          {/snippet}
        </IssueRow>
      {/if}
    {/snippet}
  </JobResultsList>
</JobPanel>

<style>
  .conflict {
    color: var(--warning);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .arrow {
    color: var(--text-tertiary);
    flex-shrink: 0;
  }

  .suggested {
    color: var(--accent);
    font-weight: 500;
  }
</style>
