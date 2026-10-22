<script lang="ts" generics="TConfig, TSchedule extends SavedSchedule<TConfig>">
  import Eye from "@lucide/svelte/icons/eye";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import Trash from "@lucide/svelte/icons/trash";
  import type { Snippet } from "svelte";
  import type { CronPreset } from "../utils/cronPresets";
  import CronScheduleField from "./CronScheduleField.svelte";
  import DataStatus from "./DataStatus.svelte";
  import {
    formatScheduleDate,
    type SavedSchedule,
    type ScheduleController,
  } from "../utils/schedules.svelte";

  let {
    controller,
    emptyMessage,
    onedit,
    badges,
    details,
    cronExpression,
    namePlaceholder,
    presets,
    oncronchange,
    unavailable,
    settings,
  }: {
    /** Holds the saved schedules, the form's name and the schedule being edited. */
    controller: ScheduleController<TConfig, TSchedule>;
    emptyMessage: string;
    /** Editing also loads the schedule's settings into the tab, which owns them. */
    onedit: (schedule: TSchedule) => void;
    /** Short labels shown beside the schedule name. */
    badges: Snippet<[TSchedule]>;
    /** Saved settings shown when the schedule is expanded. */
    details: Snippet<[TSchedule]>;
    /** The cron expression lives in the tab's configuration, which it owns. */
    cronExpression: string;
    namePlaceholder: string;
    presets?: readonly CronPreset[];
    oncronchange: (value: string) => void;
    /** Why the tab's choices cannot be saved as a schedule, which hides the form. */
    unavailable?: string;
    /** Settings the schedule kind adds beside name and timing. */
    settings?: Snippet;
  } = $props();

  function checkedFromEvent(event: Event & { currentTarget: HTMLInputElement }) {
    return event.currentTarget.checked;
  }

  function runLabel(schedule: TSchedule): string {
    switch (schedule.run_status) {
      case "queued":
        return schedule.waiting_for ? `Queued behind ${schedule.waiting_for}` : "Queued";
      case "waiting":
        return `Waiting for ${schedule.waiting_for ?? "a busy job"}`;
      case "running":
        return "Running";
      case "idle":
        return "";
    }
  }
</script>

<section class="option-card" aria-label="Schedules">
  <div class="heading-row">
    <span class="form-label">{controller.isEditing ? "Edit schedule" : "New schedule"}</span>
    {#if controller.isEditing}
      <button type="button" class="btn btn-ghost btn-sm" onclick={() => controller.clearEdit()}>
        New schedule
      </button>
    {/if}
  </div>
  {#if unavailable}
    <p class="hint">{unavailable}</p>
  {:else}
    <label class="form-row">
      <span class="field-label">Name</span>
      <input
        type="text"
        class="text-input"
        bind:value={controller.name}
        placeholder={namePlaceholder}
      />
    </label>
    {@render settings?.()}
    <CronScheduleField value={cronExpression} onchange={oncronchange} {presets} />
  {/if}

  <div class="saved">
    <div class="heading-row">
      <span class="form-label">Saved schedules</span>
      {#if controller.loading}
        <span class="hint">Loading...</span>
      {:else if controller.schedules.length === 0 && !controller.error}
        <!-- Without a list, the status below says why. -->
        <span class="hint">{emptyMessage}</span>
      {/if}
    </div>
    <DataStatus
      label="Schedules"
      error={controller.error}
      loading={controller.fetching}
      hasData={controller.schedules.length > 0}
      onretry={() => controller.reload()}
    />
    {#if !controller.loading && controller.schedules.length > 0}
      <div class="schedule-list">
        {#each controller.schedules as schedule (schedule.id)}
          {@const expanded = controller.isExpanded(schedule.id)}
          {@const running = schedule.run_status === "running"}
          <div class="schedule-row">
            <div class="schedule-main">
              <div class="schedule-title-row">
                <label class="checkbox-group schedule-enabled">
                  <input
                    type="checkbox"
                    checked={schedule.enabled}
                    onchange={(event) =>
                      void controller.setEnabled(schedule, checkedFromEvent(event))}
                  />
                  <span>{schedule.name}</span>
                </label>
                <span class={["badge", { "badge-success": schedule.enabled }]}>
                  {schedule.enabled ? "Enabled" : "Disabled"}
                </span>
                {@render badges(schedule)}
                {#if schedule.run_status !== "idle"}
                  <span
                    class={[
                      "badge",
                      {
                        "badge-accent": schedule.run_status === "running",
                        "badge-warning": schedule.run_status !== "running",
                      },
                    ]}
                    role="status">{runLabel(schedule)}</span
                  >
                {/if}
              </div>
              <div class="schedule-meta">
                <span>{schedule.cron_expression}</span>
                <span>Next: {formatScheduleDate(schedule.next_run, schedule.timezone)}</span>
              </div>
              {#if expanded}
                <div class="schedule-details">
                  {@render details(schedule)}
                  <div>
                    Last run: {formatScheduleDate(schedule.last_run_at, schedule.timezone)}
                  </div>
                </div>
              {/if}
            </div>
            <div class="schedule-actions">
              <button
                type="button"
                class={["btn btn-ghost btn-icon", { active: expanded }]}
                title={expanded ? "Hide schedule" : "View schedule"}
                aria-label={expanded ? "Hide schedule" : "View schedule"}
                aria-expanded={expanded}
                onclick={() => controller.toggleExpanded(schedule.id)}
              >
                {#if expanded}
                  <EyeOff size={15} />
                {:else}
                  <Eye size={15} />
                {/if}
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-icon"
                title="Edit schedule"
                aria-label="Edit schedule"
                onclick={() => onedit(schedule)}
              >
                <Pencil size={15} />
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-icon"
                title={running ? "Schedule is running" : "Run now with its saved options"}
                aria-label="Run schedule"
                onclick={() => void controller.runNow(schedule)}
                disabled={controller.runPending}
              >
                {#if running}
                  <LoaderCircle size={15} class="animate-spin" />
                {:else}
                  <Play size={15} />
                {/if}
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-icon text-danger"
                title="Remove schedule"
                aria-label="Remove schedule"
                onclick={() => void controller.remove(schedule)}
                disabled={controller.removePending}
              >
                <Trash size={15} />
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</section>

<style>
  .saved {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-1);
    padding-top: var(--space-3);
    border-top: var(--border-subtle);
  }

  /* As wide as the cron field's label, so both inputs start together. */
  .field-label {
    min-width: 8.5em;
  }

  .schedule-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .schedule-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
  }

  .schedule-main {
    min-width: 0;
    flex: 1;
  }

  .schedule-title-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .schedule-enabled {
    min-width: 0;
    font-weight: 600;
  }

  .schedule-meta,
  .schedule-details {
    color: var(--text-tertiary);
    font-size: var(--text-xs);
  }

  .schedule-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-top: var(--space-1);
  }

  .schedule-details {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin-top: var(--space-2);
  }

  .schedule-actions .btn.active {
    color: var(--accent);
    background: var(--accent-muted);
  }

  .schedule-actions {
    display: flex;
    gap: var(--space-1);
    flex-shrink: 0;
  }

  @media (max-width: 640px) {
    .schedule-row {
      flex-direction: column;
    }

    .schedule-actions {
      align-self: flex-end;
    }
  }
</style>
