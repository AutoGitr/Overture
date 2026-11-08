<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    label,
    for: controlId,
    hint,
    children,
  }: {
    label: string;
    /** The control the label names; without it the row is a named group. */
    for?: string;
    hint?: string;
    children?: Snippet;
  } = $props();
</script>

<!-- One setting: its name and control on one line, wrapping on narrow screens,
     with any explanation underneath. -->
<div class="field" role={controlId ? undefined : "group"} aria-label={controlId ? undefined : label}>
  <div class="field-row">
    {#if controlId}
      <label class="row-label" for={controlId}>{label}</label>
    {:else}
      <span class="row-label">{label}</span>
    {/if}
    <div class="control">{@render children?.()}</div>
  </div>
  {#if hint}<span class="hint">{hint}</span>{/if}
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  /* Inline by default: the name beside its control. A parent such as a form
     section stacks them with --field-direction: column. */
  .field-row {
    --segmented-margin: 0;
    --segmented-width: var(--field-segmented-width, auto);
    display: flex;
    flex-direction: var(--field-direction, row);
    flex-wrap: var(--field-wrap, wrap);
    align-items: var(--field-align, center);
    justify-content: space-between;
    gap: var(--space-2) var(--space-3);
  }

  /* A parent lines rows up in columns with --field-label-flex: 0 0 <width>
     and lets controls fill the rest with --field-control-flex: 1 1 0; with
     --field-control-min a control too narrow beside its name moves under it. */
  .row-label {
    flex: var(--field-label-flex, 1 1 auto);
    min-width: 0;
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-secondary);
  }

  .control {
    flex: var(--field-control-flex, 0 1 auto);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: var(--field-control-justify, flex-end);
    gap: var(--space-2);
    min-width: var(--field-control-min, 0);
    max-width: 100%;
  }

  .field-row :global(select),
  .field-row :global(input:not([type="checkbox"], [type="radio"])) {
    flex: var(--field-input-flex, 0 1 auto);
    width: auto;
    min-width: 0;
    max-width: 100%;
  }
</style>
