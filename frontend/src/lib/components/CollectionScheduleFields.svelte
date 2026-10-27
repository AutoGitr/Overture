<script module lang="ts">
  /** When collections sync and are active, at any level. */
  export type ScheduleData = {
    sync_enabled?: boolean | null;
    sync_schedule?: string | null;
    active_start_mmdd?: string | null;
    active_end_mmdd?: string | null;
    delete_when_inactive?: boolean | null;
  };

  const ON_OFF = [
    [true, "On"],
    [false, "Off"],
  ] as const;
  const REMOVE_KEEP = [
    [true, "Remove from server"],
    [false, "Keep on server"],
  ] as const;
</script>

<script lang="ts">
  import { ROUTINE_CRON_PRESETS } from "../utils/cronPresets";
  import CronScheduleField from "./CronScheduleField.svelte";
  import InheritedSelect from "./InheritedSelect.svelte";
  import type { PolicyLevel } from "./CollectionPolicyFields.svelte";

  let {
    policy,
    level,
    defaults,
    sync = true,
  }: {
    policy: ScheduleData;
    level: PolicyLevel;
    defaults?: ScheduleData;
    /** Show when criteria sync; hand-picked collections never do. */
    sync?: boolean;
  } = $props();

  const id = $props.id();
  let inherits = $derived(level !== "global");
</script>

{#if sync}
  <InheritedSelect
    label="Scheduled sync"
    {inherits}
    bind:value={policy.sync_enabled}
    inherited={defaults?.sync_enabled}
    options={ON_OFF}
  />
  <div class="form-wide">
    <CronScheduleField
      label="Sync schedule"
      value={policy.sync_schedule ?? ""}
      placeholder={inherits ? `Default (${defaults?.sync_schedule ?? ""})` : ""}
      presets={ROUTINE_CRON_PRESETS}
      onchange={(value) => (policy.sync_schedule = value.trim() || null)}
    />
  </div>
{/if}
{#if level !== "global"}
  <div class="form-label">
    <label for={`${id}-from`}>Active from (MM-DD)</label>
    <input
      id={`${id}-from`}
      maxlength="5"
      placeholder={defaults?.active_start_mmdd ?? "All year"}
      value={policy.active_start_mmdd ?? ""}
      oninput={(event) => (policy.active_start_mmdd = event.currentTarget.value.trim() || null)}
    />
    <span class="hint">Blank for all year. A range can cross New Year.</span>
  </div>
  <label class="form-label">
    Active until (MM-DD)
    <input
      maxlength="5"
      placeholder={defaults?.active_end_mmdd ?? "All year"}
      value={policy.active_end_mmdd ?? ""}
      oninput={(event) => (policy.active_end_mmdd = event.currentTarget.value.trim() || null)}
    />
  </label>
{/if}
<InheritedSelect
  label="When inactive"
  {inherits}
  bind:value={policy.delete_when_inactive}
  inherited={defaults?.delete_when_inactive}
  options={REMOVE_KEEP}
/>
