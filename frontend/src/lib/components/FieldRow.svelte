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

  .field-row {
    --segmented-margin: 0;
    --segmented-width: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
    align-items: center;
    gap: var(--space-2) var(--space-3);
    min-height: var(--control-height);

    @media (max-width: 480px) {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .row-label {
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .control {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-2);
    min-width: 0;
  }

  .field-row :global(select),
  .field-row :global(input[type="number"]) {
    width: auto;
    max-width: 100%;
  }
</style>
