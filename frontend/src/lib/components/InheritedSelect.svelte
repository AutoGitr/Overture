<script lang="ts" generics="T extends string | boolean">
  import FieldRow from "./FieldRow.svelte";

  let {
    label,
    inherits,
    value = $bindable(),
    inherited,
    options,
    hint,
    disabled = false,
  }: {
    label: string;
    /** Offer Default, which inherits the value named in it. */
    inherits: boolean;
    value: T | null | undefined;
    inherited?: T | null;
    options: readonly (readonly [T, string])[];
    hint?: string;
    /** Keep the choice but take no input, as when another setting makes it moot. */
    disabled?: boolean;
  } = $props();

  const id = $props.id();
  let inheritedLabel = $derived(options.find(([option]) => option === inherited)?.[1]);
</script>

<FieldRow {label} for={id} {hint}>
  <select
    {id}
    {disabled}
    value={value == null ? "" : String(value)}
    onchange={(event) => {
      const raw = event.currentTarget.value;
      value = options.find(([option]) => String(option) === raw)?.[0] ?? null;
    }}
  >
    {#if inherits}
      <option value="">{inheritedLabel ? `Default (${inheritedLabel})` : "Default"}</option>
    {/if}
    {#each options as [option, name] (String(option))}
      <option value={String(option)}>{name}</option>
    {/each}
  </select>
</FieldRow>
