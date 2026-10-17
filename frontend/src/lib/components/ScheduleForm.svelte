<script lang="ts" generics="TConfig, TSchedule extends SavedSchedule<TConfig>">
  import type { CronPreset } from "../utils/cronPresets";
  import type { Snippet } from "svelte";
  import type { SavedSchedule, ScheduleController } from "../utils/schedules.svelte";
  import CronScheduleField from "./CronScheduleField.svelte";

  let {
    controller,
    cronExpression,
    namePlaceholder,
    presets,
    oncronchange,
    children,
  }: {
    /** Holds the form's name and state and the schedule being edited. */
    controller: ScheduleController<TConfig, TSchedule>;
    /** The cron expression lives in the tab's configuration, which it owns. */
    cronExpression: string;
    namePlaceholder: string;
    presets?: readonly CronPreset[];
    oncronchange: (value: string) => void;
    /** Settings the schedule kind adds beside name, state and timing. */
    children?: Snippet;
  } = $props();
</script>

<div class="option-card">
  <div class="schedule-card-header">
    <span class="form-label">Cron</span>
    {#if controller.isEditing}
      <button type="button" class="btn btn-ghost btn-sm" onclick={() => controller.clearEdit()}>
        New schedule
      </button>
    {/if}
  </div>
  <div class="schedule-fields">
    <label class="field-block">
      <span class="form-label">Name</span>
      <input type="text" bind:value={controller.name} placeholder={namePlaceholder} />
    </label>
    <label class="checkbox-group">
      <input type="checkbox" bind:checked={controller.enabled} />
      <span>Enabled</span>
    </label>
  </div>
  {@render children?.()}
  <CronScheduleField value={cronExpression} onchange={oncronchange} {presets} />
</div>

<style>
  .schedule-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .schedule-fields {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--space-3);
    align-items: end;
    margin-top: var(--space-2);
  }

  .field-block {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .field-block input {
    width: 100%;
  }

  @media (max-width: 640px) {
    .schedule-fields {
      grid-template-columns: 1fr;
    }
  }
</style>
