<script lang="ts" generics="TConfig, TSchedule extends SavedSchedule<TConfig>">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Play from "@lucide/svelte/icons/play";
  import Trash from "@lucide/svelte/icons/trash";
  import type { Snippet } from "svelte";
  import type { CronPreset } from "../utils/cronPresets";
  import CronScheduleField from "./CronScheduleField.svelte";
  import DataStatus from "./DataStatus.svelte";
  import Disclosure from "./Disclosure.svelte";
  import FieldRow from "./FieldRow.svelte";
  import {
    formatRunSummary,
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

  const nameId = $props.id();
  let editing = $derived(
    controller.schedules.find((schedule) => schedule.id === controller.editingId),
  );

  function checkedFromEvent(event: Event & { currentTarget: HTMLInputElement }) {
    return event.currentTarget.checked;
  }

  function summary(schedule: TSchedule): string {
    return [
      schedule.cron_expression,
      `Next: ${formatScheduleDate(schedule.next_run, schedule.timezone)}`,
      schedule.last_run_at &&
        `Last run: ${formatScheduleDate(schedule.last_run_at, schedule.timezone)}`,
      schedule.last_run && `Result: ${formatRunSummary(schedule.last_run)}`,
    ]
      .filter(Boolean)
      .join(" · ");
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

<section class="option-card schedules" aria-label="Schedules">
  <div class="heading-row">
    <span class="form-label">
      {editing ? `Editing "${editing.name}"` : "New schedule"}
    </span>
  </div>
  {#if unavailable}
    <p class="hint">{unavailable}</p>
  {:else}
    <FieldRow label="Name" for={nameId}>
      <input
        id={nameId}
        type="text"
        class="text-input"
        bind:value={controller.name}
        placeholder={namePlaceholder}
      />
    </FieldRow>
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
          {@const running = schedule.run_status === "running"}
          {@const isEdited = controller.editingId === schedule.id}
          <div class={["schedule-row", { edited: isEdited }]}>
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
              <Disclosure
                title={summary(schedule)}
                open={controller.isExpanded(schedule.id)}
                ontoggle={() => controller.toggleExpanded(schedule.id)}
                --disclosure-padding="var(--space-1) 0"
                --disclosure-title-size="var(--text-xs)"
                --disclosure-title-weight="400"
                --disclosure-title-color="var(--text-tertiary)"
              >
                <div class="schedule-details">
                  {@render details(schedule)}
                </div>
              </Disclosure>
            </div>
            <div class="schedule-actions">
              <button
                type="button"
                class={["btn btn-ghost btn-icon", { active: isEdited }]}
                title={isEdited ? "Cancel editing" : "Edit schedule"}
                aria-label={isEdited ? "Cancel editing" : "Edit schedule"}
                aria-pressed={isEdited}
                onclick={() => (isEdited ? controller.clearEdit() : onedit(schedule))}
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

  /* Every setting's name shares one column and its control fills the rest,
     including those the schedule kind adds. */
  .schedules {
    --field-label-flex: 0 0 8.5em;
    --field-control-flex: 1 1 0;
    --field-input-flex: 1 1 auto;
    --field-control-justify: flex-start;
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

  .schedule-row.edited {
    border-color: var(--accent);
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

  .schedule-details {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    color: var(--text-tertiary);
    font-size: var(--text-xs);
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
