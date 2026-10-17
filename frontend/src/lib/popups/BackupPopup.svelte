<script lang="ts">
  import Clock from "@lucide/svelte/icons/clock";
  import DatabaseBackup from "@lucide/svelte/icons/database-backup";
  import HardDrive from "@lucide/svelte/icons/hard-drive";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import {
    createBackupMutation,
    getBackupScheduleOptions,
    listBackupsOptions,
    updateBackupScheduleMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    BackupRetentionOutput,
    BackupScheduleResponse,
  } from "../../generated/rest/types.gen";
  import { invalidateTags } from "../rest/cache";
  import { backupState } from "../stores/jobStates.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { DEFAULT_CRON_EXPRESSION } from "../utils/cronPresets";
  import { delayedFlag } from "../utils/delayedFlag.svelte";
  import { errorMessage } from "../utils/errors";
  import { formatBytes, formatDateInTimezone } from "../utils/popupFormat";
  import PopupShell from "../components/PopupShell.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PendingButton from "../components/PendingButton.svelte";
  import CronScheduleField from "../components/CronScheduleField.svelte";

  const queryClient = useQueryClient();

  const RETENTION_FIELDS = [
    { key: "latest", label: "Latest", min: 1 },
    { key: "daily", label: "Daily", min: 0 },
    { key: "weekly", label: "Weekly", min: 0 },
    { key: "monthly", label: "Monthly", min: 0 },
  ] as const;

  let enabled = $state(false);
  let cronExpression = $state(DEFAULT_CRON_EXPRESSION);
  let retention = $state<BackupRetentionOutput | null>(null);
  const scheduleQuery = createQuery(() => getBackupScheduleOptions());
  const backupsQuery = createQuery(() => listBackupsOptions());
  let nextRun = $derived(scheduleQuery.data?.next_run);
  let timezoneLabel = $derived(scheduleQuery.data?.timezone ?? "UTC");
  let backups = $derived(backupsQuery.data?.backups ?? []);
  let draftInitialised = $state(false);
  let canEdit = $derived(draftInitialised && !scheduleQuery.isError);
  const feedback = createNotifier();

  const backupNowRequest = createMutation(() => createBackupMutation());
  const saveScheduleRequest = createMutation(() => updateBackupScheduleMutation());
  let backingUp = $derived(backupNowRequest.isPending || backupState.running);
  const showBackingUp = delayedFlag(() => backingUp);

  $effect(() => {
    if (scheduleQuery.data && !draftInitialised) {
      loadDraft(scheduleQuery.data);
      draftInitialised = true;
    }
  });

  function loadDraft(schedule: BackupScheduleResponse) {
    enabled = schedule.enabled;
    cronExpression = schedule.cron_expression;
    retention = { ...schedule.retention };
  }

  async function saveSchedule() {
    if (!canEdit) return;
    feedback.clear();
    try {
      const updated = await saveScheduleRequest.mutateAsync({
        body: {
          enabled,
          cron_expression: cronExpression,
          retention,
        },
      });
      queryClient.setQueryData(getBackupScheduleOptions().queryKey, updated);
      loadDraft(updated);
      feedback.success("Backup schedule saved.");
    } catch (e) {
      feedback.error(errorMessage(e, "Failed to save backup schedule"));
    }
  }

  async function backupNow() {
    if (backingUp) return;
    feedback.clear();
    try {
      const { filename } = await backupNowRequest.mutateAsync({});
      feedback.success(`Saved ${filename}.`, { title: "Backup complete" });
      await invalidateTags(["backups"]);
    } catch (e) {
      feedback.error(errorMessage(e, "Backup failed"));
    }
  }
</script>

<PopupShell title="Backup" width="min(740px,94vw)" onclose={() => uiState.closePopup()}>
  <section class="option-card">
    <div class="section-header">
      <DatabaseBackup size={16} class="section-icon" />
      <span class="form-label mb-0">Manual Backup</span>
    </div>
    <p class="hint">
      Backups are saved to <code>/config/backups/</code>.
    </p>
    <div class="backup-now-row">
      <button
        class="btn btn-primary"
        onclick={backupNow}
        disabled={backingUp}
        aria-busy={backingUp}
      >
        {#if showBackingUp.current}
          <LoaderCircle size={15} class="animate-spin" />
          Backing up...
        {:else}
          <DatabaseBackup size={15} />
          Backup Now
        {/if}
      </button>
    </div>
  </section>

  <section class="option-card">
    <div class="section-header">
      <Clock size={16} class="section-icon" />
      <span class="form-label mb-0">Scheduled Backups</span>
    </div>

    <DataStatus
      label="backup schedule"
      error={scheduleQuery.error}
      loading={scheduleQuery.isFetching}
      hasData={scheduleQuery.data !== undefined}
      onretry={() => scheduleQuery.refetch()}
    />
    <fieldset
      class="schedule-form"
      disabled={!canEdit || saveScheduleRequest.isPending}
      inert={saveScheduleRequest.isPending}
    >
      <div class="schedule-fields">
        <label class="form-row justify-between">
          <span>Enable scheduled backups</span>
          <input type="checkbox" bind:checked={enabled} />
        </label>

        <CronScheduleField value={cronExpression} onchange={(value) => (cronExpression = value)} />

        <fieldset class="retention">
          <legend>Backups to keep</legend>
          <p class="hint">
            The latest backups, plus the newest backup of each recent day, week and month. 0 turns a
            period off.
          </p>
          {#if retention}
            <div class="retention-fields">
              {#each RETENTION_FIELDS as field (field.key)}
                <label class="retention-field">
                  <span>{field.label}</span>
                  <input
                    type="number"
                    class="number-input compact"
                    min={field.min}
                    bind:value={retention[field.key]}
                  />
                </label>
              {/each}
            </div>
          {/if}
        </fieldset>
      </div>

      {#if draftInitialised}<div class="next-run">
          {#if enabled && nextRun}
            Next run: <strong>{formatDateInTimezone(nextRun, timezoneLabel)}</strong>
            ({timezoneLabel})
          {:else if enabled}
            Next run will be shown after saving.
          {:else}
            Schedule is disabled.
          {/if}
        </div>{/if}

      <div class="schedule-save-row">
        <PendingButton
          class="btn btn-primary btn-sm"
          onclick={saveSchedule}
          pending={saveScheduleRequest.isPending}
          pendingLabel="Saving..."
        >
          Save Schedule
        </PendingButton>
      </div>
    </fieldset>
  </section>

  <section class="option-card">
    <div class="section-header">
      <HardDrive size={16} class="section-icon" />
      <span class="form-label mb-0">
        Existing Backups
        {#if backups.length > 0}
          <span class="count-badge">{backups.length}</span>
        {/if}
      </span>
    </div>

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
        {#each backups as b (b.filename)}
          <li class="backup-item">
            <span class="backup-name">{b.filename}</span>
            <span class="backup-meta">
              <span class="backup-size">{formatBytes(b.size_bytes)}</span>
              <span class="backup-date">{formatDateInTimezone(b.created_at, timezoneLabel)}</span>
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
  {#snippet footer()}
    <button class="btn btn-ghost" onclick={() => uiState.closePopup()}>Close</button>
  {/snippet}
</PopupShell>

<style>
  .section-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }

  .section-header :global(.section-icon) {
    color: var(--accent);
    flex-shrink: 0;
  }

  .backup-now-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .backup-now-row .btn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .schedule-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }

  .compact {
    width: 80px;
    text-align: right;
  }

  .retention {
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }

  .retention legend {
    padding: 0;
  }

  .retention-fields {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--space-3);
  }

  .retention-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }

  .retention-field .compact {
    width: 100%;
  }

  @media (max-width: 480px) {
    .retention-fields {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  .next-run {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    margin-bottom: var(--space-3);
  }

  .schedule-save-row {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-3);
  }

  .schedule-form {
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }

  .count-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--text-xs);
    font-weight: 600;
    background: var(--accent-muted);
    color: var(--accent);
    border-radius: 99px;
    padding: 0 6px;
    min-width: 20px;
    height: 18px;
    margin-left: var(--space-2);
    vertical-align: middle;
  }

  .backup-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-height: 34vh;
    overflow-y: auto;
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
