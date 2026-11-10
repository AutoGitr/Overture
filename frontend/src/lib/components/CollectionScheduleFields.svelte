<script module lang="ts">
  import type { ScheduleData } from "../utils/collectionForms.svelte";

  const REMOVE_KEEP = [
    [true, "Remove from server"],
    [false, "Keep on server"],
  ] as const;
</script>

<script lang="ts">
  import FieldRow from "./FieldRow.svelte";
  import InheritedSelect from "./InheritedSelect.svelte";
  import type { PolicyLevel } from "./CollectionPolicyFields.svelte";

  let {
    policy = $bindable(),
    level,
    defaults,
  }: {
    policy: ScheduleData;
    level: PolicyLevel;
    defaults?: ScheduleData;
  } = $props();

  const id = $props.id();
  let inherits = $derived(level !== "global");
</script>

{#if level !== "global"}
  <FieldRow
    label="Active from (MM-DD)"
    for={`${id}-from`}
    hint="Blank for all year. A range can cross New Year."
  >
    <input
      id={`${id}-from`}
      maxlength="5"
      size="8"
      placeholder={defaults?.active_start_mmdd ?? "All year"}
      value={policy.active_start_mmdd ?? ""}
      oninput={(event) => (policy.active_start_mmdd = event.currentTarget.value.trim() || null)}
    />
  </FieldRow>
  <FieldRow label="Active until (MM-DD)" for={`${id}-until`}>
    <input
      id={`${id}-until`}
      maxlength="5"
      size="8"
      placeholder={defaults?.active_end_mmdd ?? "All year"}
      value={policy.active_end_mmdd ?? ""}
      oninput={(event) => (policy.active_end_mmdd = event.currentTarget.value.trim() || null)}
    />
  </FieldRow>
{/if}
<InheritedSelect
  label="When inactive"
  {inherits}
  bind:value={policy.delete_when_inactive}
  inherited={defaults?.delete_when_inactive}
  options={REMOVE_KEEP}
/>
