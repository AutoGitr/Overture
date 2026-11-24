<script lang="ts">
  import Clock from "@lucide/svelte/icons/clock";
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import {
    getBackupScheduleOptions,
    updateBackupScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import type { BackupScheduleResponse } from "../../../generated/rest/types.gen";
  import { invalidateTags } from "../../rest/cache";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { draftOf } from "../../utils/draft.svelte";
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

  /** The schedule's editable part; null until it loads. */
  const draft = draftOf(() => scheduleQuery.data && editable(scheduleQuery.data));

  function editable({ enabled, cron_expression, retention }: BackupScheduleResponse) {
    return { enabled, cron_expression, retention };
  }
  let canEdit = $derived(draft.current !== null && !scheduleQuery.isError);
  let nextRun = $derived(scheduleQuery.data?.next_run);
  let timezone = $derived(scheduleQuery.data?.timezone ?? "UTC");

  async function saveSchedule() {
    if (!canEdit || !draft.current) return;
    feedback.clear();
    try {
      const updated = await saveScheduleRequest.mutateAsync({
        body: $state.snapshot(draft.current),
      });
      queryClient.setQueryData(getBackupScheduleOptions().queryKey, updated);
      draft.current = editable(updated);
      // Saving applies the retention to the existing backups at once.
      await invalidateTags(["backups"]);
      feedback.success("Backup schedule saved.");
    } catch (e) {
      feedback.error(errorMessage(e, "Failed to save backup schedule"));
    }
  }
</script>

<BackupSection icon={Clock} title="Scheduled backups">
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
    {#if draft.current}
      {@const schedule = draft.current}
      <div class="schedule-fields">
        <label class="form-row justify-between">
          <span>Enable scheduled backups</span>
          <input type="checkbox" bind:checked={schedule.enabled} />
        </label>

        <CronScheduleField
          value={schedule.cron_expression}
          onchange={(value) => (schedule.cron_expression = value)}
        />

        <fieldset class="retention">
          <legend>Backups to keep</legend>
          <p class="hint">
            The latest backups, plus the newest backup of each recent day, week and month. 0 turns
            a period off. Saving applies it to the existing backups.
          </p>
          <div class="retention-fields">
            {#each RETENTION_FIELDS as field (field.key)}
              <label class="retention-field">
                <span>{field.label}</span>
                <input
                  type="number"
                  class="number-input"
                  min={field.min}
                  bind:value={schedule.retention[field.key]}
                />
              </label>
            {/each}
          </div>
        </fieldset>
      </div>

      <div class="next-run">
        {#if schedule.enabled && nextRun}
          Next run: <strong>{formatDateInTimezone(nextRun, timezone)}</strong>
          ({timezone})
        {:else if schedule.enabled}
          Next run will be shown after saving.
        {:else}
          Schedule is disabled.
        {/if}
      </div>
    {/if}

    <div class="actions-row">
      <PendingButton
        class="btn btn-primary btn-sm"
        onclick={saveSchedule}
        pending={saveScheduleRequest.isPending}
        pendingLabel="Saving..."
      >
        Save schedule
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
    --field-label-flex: 0 0 8.5em;
    --field-control-flex: 1 1 0;
    --field-input-flex: 1 1 auto;
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

</style>
