<script lang="ts" generics="T extends string | boolean">
  import FieldRow from "./FieldRow.svelte";
  import Select from "./Select.svelte";

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
  let choices = $derived([
    ...(inherits
      ? [{ value: null, label: inheritedLabel ? `Default (${inheritedLabel})` : "Default" }]
      : []),
    ...options.map(([option, name]) => ({ value: option, label: name })),
  ]);
</script>

<FieldRow {label} for={id} {hint}>
  <Select
    {id}
    {disabled}
    options={choices}
    bind:value={() => value ?? null, (next) => (value = next)}
  />
</FieldRow>
