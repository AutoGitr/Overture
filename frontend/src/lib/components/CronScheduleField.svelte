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

<label class="form-row">
  <span class="cron-label">{label}</span>
  <input
    type="text"
    class="text-input text-input-mono"
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
  <span class="hint">minute hour day month weekday</span>
</div>

<style>
  .cron-label {
    min-width: 8.5em;
  }

  .preset-row {
    display: flex;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    flex-wrap: wrap;
  }

  .preset-row .hint {
    margin-left: auto;
  }
</style>
