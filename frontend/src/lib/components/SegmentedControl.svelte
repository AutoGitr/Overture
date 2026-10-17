<script lang="ts" generics="T extends string">
  let {
    label,
    options,
    value = $bindable(),
  }: {
    /** Accessible name of the radio group. */
    label: string;
    options: readonly (readonly [T, string])[];
    value: T;
  } = $props();

  const name = $props.id();
</script>

<div class="segmented-control" role="radiogroup" aria-label={label}>
  {#each options as [optionValue, optionLabel] (optionValue)}
    <label class="segment-btn" class:active={value === optionValue}>
      <input type="radio" {name} value={optionValue} bind:group={value} class="sr-only" />
      <span>{optionLabel}</span>
    </label>
  {/each}
</div>
