<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import JobCount from "./JobCount.svelte";
  import JobElapsedTime from "./JobElapsedTime.svelte";
  import JobResults from "./JobResults.svelte";
  import JobResultsList from "./JobResultsList.svelte";
  import JobResultPagination from "./JobResultPagination.svelte";
  import type { AuditStatus, ServerAuditResult } from "../../generated/ws";
  import type { SelectionGroupsOf } from "../stores/collectingJobState.svelte";
  import { serverAuditFixState } from "../stores/serverAuditFixState.svelte";
  import {
    serverAuditState,
    type SelectableServerAuditResult,
  } from "../stores/serverAuditState.svelte";
  import { ASSET_BADGES, ASSET_LABELS } from "../utils/artTypes";
  import { AUDIT_STATUS_LABELS, auditRowKey } from "../utils/serverAuditPopup";

  let {
    selectedArtCount,
    selectedThemeCount,
  }: {
    selectedArtCount: number;
    selectedThemeCount: number;
  } = $props();

  /** Art types in their usual order, then statuses in their labels' order. */
  const GROUP_ORDER = [
    ...Object.keys(ASSET_LABELS).map((type) => `type:${type}`),
    ...Object.keys(AUDIT_STATUS_LABELS).map((status) => `status:${status}`),
  ];

  const groupsOf: SelectionGroupsOf<ServerAuditResult> = (result) => [
    [`type:${result.art_type}`, ASSET_LABELS[result.art_type]],
    [`status:${result.status}`, AUDIT_STATUS_LABELS[result.status]],
  ];

  let locked = $derived(serverAuditState.running || serverAuditFixState.running);

  const STATUS_BADGES: Partial<Record<AuditStatus, string>> = {
    phash_match: "badge-success",
    phash_mismatch: "badge-warning",
    error: "badge-danger",
  };

  /** A row being fixed whose outcome the server has not settled yet. */
  function awaitingServer(result: SelectableServerAuditResult): boolean {
    return (
      serverAuditFixState.pending.has(auditRowKey(result)) &&
      !result.refreshed &&
      !result.refresh_error
    );
  }
</script>

<JobResults progress={serverAuditState.progress} log={serverAuditState.log}>
  {#snippet stats()}
    <div class="stats-row">
      <JobCount job={serverAuditState} unit="files" />
      <div class="stat-item" title="Files that differ from what the server shows">
        mismatches: <span class="stat-value">{serverAuditState.found}</span>
      </div>
      <div class="stat-item">
        errors: <span class="stat-value text-danger">{serverAuditState.errors}</span>
      </div>
      <JobElapsedTime
        startedAt={serverAuditState.started_at}
        finishedAt={serverAuditState.finished_at}
      />
    </div>
  {/snippet}

  <JobResultsList
    itemCount={serverAuditState.items.length}
    itemSize={76}
    heading="{serverAuditState.items.length} actionable results on this page"
    subtitle={serverAuditState.running
      ? "Results update live while auditing"
      : `${selectedArtCount} art, ${selectedThemeCount} theme selected on this page`}
    emptyLabel="No audit results."
    showEmpty={Boolean(serverAuditState.finished_at)}
    selectedCount={serverAuditState.selectedItems.length}
    actionableCount={serverAuditState.actionableItems.length}
    groups={serverAuditState.selectionGroups(groupsOf, GROUP_ORDER)}
    running={locked}
    onSelectAll={(checked) => serverAuditState.setSelected(checked)}
    onToggleGroup={(key) => serverAuditState.toggleGroup(groupsOf, key)}
  >
    {#snippet row(idx: number, style: string)}
      {@const result = serverAuditState.items[idx]}
      {#if result}
        <label
          class="issue-item"
          class:issue-flagged={result.status !== "phash_match"}
          class:issue-dimmed={result.refreshed}
          {style}
        >
          <span class="issue-checkbox">
            <input
              type="checkbox"
              checked={result.selected && serverAuditState.isActionable(result)}
              disabled={locked || !serverAuditState.isActionable(result)}
              onclick={(event) => serverAuditState.toggle(idx, event.shiftKey)}
            />
          </span>
          <span class="issue-details">
            <span class="issue-filenames">
              <span class="issue-current truncate" title={result.title}>{result.title}</span>
              <span class="badge {ASSET_BADGES[result.art_type]}"
                >{ASSET_LABELS[result.art_type]}</span
              >
              <span class="badge {STATUS_BADGES[result.status] ?? 'badge-muted'}">
                {AUDIT_STATUS_LABELS[result.status]}
              </span>
              {#if result.hamming !== null && result.hamming !== undefined}
                <span class="badge badge-accent">d={result.hamming}</span>
              {/if}
              {#if result.kind === "theme" && result.local_duration !== null && result.local_duration !== undefined}
                <span class="badge badge-muted">local {Math.round(result.local_duration)}s</span>
              {/if}
              {#if result.kind === "theme" && result.server_duration !== null && result.server_duration !== undefined}
                <span class="badge badge-muted">server {Math.round(result.server_duration)}s</span>
              {/if}
            </span>
            <span class="issue-meta">
              {#if result.reason}
                <span class="truncate" title={result.reason}>{result.reason}</span>
              {/if}
              {#if result.local_path}
                <span class="issue-folder truncate" title={result.local_path}
                  >{result.local_path}</span
                >
              {/if}
              {#if result.refresh_error}
                <span class="status-err truncate" title={result.refresh_error}
                  >{result.refresh_error}</span
                >
              {/if}
            </span>
          </span>
          <span class="issue-status">
            {#if result.refreshed}
              <span class="status-ok" title="The media server now shows the local file">Fixed</span>
            {:else if result.refresh_error}
              <span class="status-err" title={result.refresh_error}>Not fixed</span>
            {:else if awaitingServer(result)}
              <span title="Waiting for the media server to show the local file">
                <LoaderCircle size={14} class="animate-spin" />
              </span>
            {/if}
          </span>
        </label>
      {/if}
    {/snippet}
  </JobResultsList>
  <JobResultPagination page={serverAuditState.page} running={serverAuditState.running} />
</JobResults>
