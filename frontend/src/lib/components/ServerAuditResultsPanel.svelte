<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import IssueRow from "./IssueRow.svelte";
  import JobPanel from "./JobPanel.svelte";
  import JobResultsList from "./JobResultsList.svelte";
  import type { AuditStatus } from "../../generated/ws";
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

<JobPanel
  job={serverAuditState}
  unit="files"
  stats={[
    {
      label: "mismatches",
      value: serverAuditState.found,
      title: "Files that differ from what the server shows",
    },
    { label: "errors", value: serverAuditState.errors, tone: "danger" },
  ]}
>
  <JobResultsList
    itemCount={serverAuditState.shown.length}
    total={serverAuditState.items.length}
    itemSize={76}
    noun="results"
    subtitle="{selectedArtCount} art, {selectedThemeCount} theme selected"
    emptyLabel="No audit results."
    showEmpty={Boolean(serverAuditState.finished_at)}
    selectedCount={serverAuditState.selectedItems.length}
    hiddenSelectedCount={serverAuditState.hiddenSelectedCount}
    actionableCount={serverAuditState.actionableItems.length}
    groups={serverAuditState.groups}
    running={locked}
    findings={serverAuditState}
    onSelectAll={(checked) => serverAuditState.setSelected(checked)}
    onToggleGroup={(key) => serverAuditState.toggleGroup(key)}
  >
    {#snippet row(idx: number, style: string)}
      {@const shown = serverAuditState.shown[idx]}
      {#if shown}
        {@const { index, item: result } = shown}
        <IssueRow
          {style}
          checked={result.selected && serverAuditState.isActionable(result)}
          disabled={locked || !serverAuditState.isActionable(result)}
          dimmed={result.refreshed}
          flagged={result.status !== "phash_match"}
          ontoggle={(range) => serverAuditState.toggle(index, range)}
        >
          {#snippet title()}
            <span class="issue-name truncate" title={result.title}>{result.title}</span>
            <span class="badge {ASSET_BADGES[result.art_type]}"
              >{ASSET_LABELS[result.art_type]}</span
            >
            <span class="badge {STATUS_BADGES[result.status] ?? 'badge-muted'}">
              {AUDIT_STATUS_LABELS[result.status]}
            </span>
            {#if result.hamming != null}
              <span class="badge badge-accent">d={result.hamming}</span>
            {/if}
            {#if result.kind === "theme" && result.local_duration != null}
              <span class="badge badge-muted">local {Math.round(result.local_duration)}s</span>
            {/if}
            {#if result.kind === "theme" && result.server_duration != null}
              <span class="badge badge-muted">server {Math.round(result.server_duration)}s</span>
            {/if}
          {/snippet}
          {#snippet meta()}
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
          {/snippet}
          {#snippet status()}
            {#if result.refreshed}
              <span class="status-ok" title="The media server now shows the local file">Fixed</span>
            {:else if result.refresh_error}
              <span class="status-err" title={result.refresh_error}>Not fixed</span>
            {:else if awaitingServer(result)}
              <span title="Waiting for the media server to show the local file">
                <LoaderCircle size={14} class="animate-spin" />
              </span>
            {/if}
          {/snippet}
        </IssueRow>
      {/if}
    {/snippet}
  </JobResultsList>
</JobPanel>
