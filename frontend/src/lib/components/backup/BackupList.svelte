<script lang="ts">
  import HardDrive from "@lucide/svelte/icons/hard-drive";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getBackupScheduleOptions,
    listBackupsOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { formatBytes, formatDateInTimezone } from "../../utils/popupFormat";
  import DataStatus from "../DataStatus.svelte";
  import BackupSection from "./BackupSection.svelte";

  const backupsQuery = createQuery(() => listBackupsOptions());
  // Dates read in the schedule's timezone, as its next run does.
  const scheduleQuery = createQuery(() => getBackupScheduleOptions());
  let backups = $derived(backupsQuery.data?.backups ?? []);
  let timezone = $derived(scheduleQuery.data?.timezone ?? "UTC");
</script>

<BackupSection icon={HardDrive} title="Existing Backups" count={backups.length}>
  <DataStatus
    label="backups"
    error={backupsQuery.error}
    loading={backupsQuery.isFetching}
    hasData={backupsQuery.data !== undefined}
    onretry={() => backupsQuery.refetch()}
  />
  {#if backupsQuery.isSuccess && backups.length === 0}
    <p class="hint">No backups yet.</p>
  {:else if backups.length > 0}
    <ul class="backup-list">
      {#each backups as backup (backup.filename)}
        <li class="backup-item">
          <span class="backup-name">{backup.filename}</span>
          <span class="backup-meta">
            <span class="backup-size">{formatBytes(backup.size_bytes)}</span>
            <span>{formatDateInTimezone(backup.created_at, timezone)}</span>
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</BackupSection>

<style>
  .backup-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-height: 34dvh;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-right: var(--space-1);
  }

  .backup-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
    flex-wrap: wrap;
  }

  .backup-name {
    font-family: var(--font-mono, monospace);
    color: var(--text-primary);
    flex: 1;
    min-width: 0;
    word-break: break-all;
  }

  .backup-meta {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-shrink: 0;
    color: var(--text-tertiary);
  }

  .backup-size {
    min-width: 55px;
    text-align: right;
  }
</style>
