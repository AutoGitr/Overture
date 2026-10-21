<script lang="ts">
  import {
    DEFAULT_CRON_EXPRESSION,
    ROUTINE_CRON_PRESETS,
    type CronPreset,
  } from "../utils/cronPresets";

  let {
    value,
    onchange,
    disabled = false,
    presets = ROUTINE_CRON_PRESETS,
    label = "Cron expression",
    placeholder = DEFAULT_CRON_EXPRESSION,
  }: {
    value: string;
    onchange: (value: string) => void;
    disabled?: boolean;
    presets?: readonly CronPreset[];
    label?: string;
    placeholder?: string;
  } = $props();
</script>

<label class="cron-field">
  <span>{label}</span>
  <input
    type="text"
    class="text-input"
    {value}
    {placeholder}
    {disabled}
    oninput={(event) => onchange(event.currentTarget.value)}
  />
</label>

<div class="preset-row">
  {#each presets as preset (preset.value)}
    <button
      class="btn btn-ghost btn-sm"
      type="button"
      {disabled}
      onclick={() => onchange(preset.value)}
    >
      {preset.label}
    </button>
  {/each}
</div>

<p class="hint">
  Five fields: minute hour day month weekday. Example:
  <code>0 3 * * *</code> runs daily at 03:00.
</p>

<style>
  .cron-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .preset-row {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
</style>
