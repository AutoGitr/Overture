<script lang="ts">
  import Clock from "@lucide/svelte/icons/clock";
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import {
    getBackupScheduleOptions,
    updateBackupScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    BackupRetentionOutput,
    BackupScheduleResponse,
  } from "../../../generated/rest/types.gen";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { DEFAULT_CRON_EXPRESSION } from "../../utils/cronPresets";
  import { errorMessage } from "../../utils/errors";
  import { formatDateInTimezone } from "../../utils/popupFormat";
  import CronScheduleField from "../CronScheduleField.svelte";
  import DataStatus from "../DataStatus.svelte";
  import PendingButton from "../PendingButton.svelte";
  import BackupSection from "./BackupSection.svelte";

  const RETENTION_FIELDS = [
    { key: "latest", label: "Latest", min: 1 },
    { key: "daily", label: "Daily", min: 0 },
    { key: "weekly", label: "Weekly", min: 0 },
    { key: "monthly", label: "Monthly", min: 0 },
  ] as const;

  const queryClient = useQueryClient();
  const feedback = createNotifier();
  const scheduleQuery = createQuery(() => getBackupScheduleOptions());
  const saveScheduleRequest = createMutation(() => updateBackupScheduleMutation());

  let enabled = $state(false);
  let cronExpression = $state(DEFAULT_CRON_EXPRESSION);
  let retention = $state<BackupRetentionOutput | null>(null);
  let draftInitialised = $state(false);
  let canEdit = $derived(draftInitialised && !scheduleQuery.isError);
  let nextRun = $derived(scheduleQuery.data?.next_run);
  let timezone = $derived(scheduleQuery.data?.timezone ?? "UTC");

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
        body: { enabled, cron_expression: cronExpression, retention },
      });
      queryClient.setQueryData(getBackupScheduleOptions().queryKey, updated);
      loadDraft(updated);
      feedback.success("Backup schedule saved.");
    } catch (e) {
      feedback.error(errorMessage(e, "Failed to save backup schedule"));
    }
  }
</script>

<BackupSection icon={Clock} title="Scheduled Backups">
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
                  class="number-input"
                  min={field.min}
                  bind:value={retention[field.key]}
                />
              </label>
            {/each}
          </div>
        {/if}
      </fieldset>
    </div>

    {#if draftInitialised}
      <div class="next-run">
        {#if enabled && nextRun}
          Next run: <strong>{formatDateInTimezone(nextRun, timezone)}</strong>
          ({timezone})
        {:else if enabled}
          Next run will be shown after saving.
        {:else}
          Schedule is disabled.
        {/if}
      </div>
    {/if}

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
</BackupSection>

<style>
  .schedule-form,
  .retention {
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }

  .schedule-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }

  .retention legend {
    padding: 0;
  }

  .retention-fields {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--space-3);
  }

  @media (max-width: 480px) {
    .retention-fields {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  .retention-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }

  .retention-field input {
    width: 100%;
    text-align: right;
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
</style>
