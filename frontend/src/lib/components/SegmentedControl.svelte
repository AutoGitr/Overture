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
    <label class={["segment-btn", { active: value === optionValue }]}>
      <input type="radio" {name} value={optionValue} bind:group={value} class="sr-only" />
      <span>{optionLabel}</span>
    </label>
  {/each}
</div>

<style>
  /* A parent can give every option the same share of a fixed width with
     --segment-flex: 1 1 0 and keep them on one line with --segmented-wrap. */
  .segmented-control {
    display: flex;
    flex-wrap: var(--segmented-wrap, wrap);
    background: var(--track-bg);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 2px;
    gap: 2px;
    width: var(--segmented-width, 100%);
    max-width: 100%;
    margin-top: var(--segmented-margin, var(--space-2));
    box-sizing: border-box;
  }

  .segment-btn {
    flex: var(--segment-flex, 1 1 auto);
    min-width: 0;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    text-align: center;
    padding: var(--space-1) var(--space-2);
    border-radius: calc(var(--radius-sm) - 2px);
    font-size: var(--text-xs);
    font-weight: 500;
    color: var(--text-secondary);
    cursor: pointer;
    white-space: nowrap;
  }

  .segment-btn span {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .segment-btn:hover {
    color: var(--text-secondary);
    background: var(--bg-hover);
  }

  .segment-btn.active {
    background: var(--accent-fill);
    color: var(--accent-text);
    font-weight: 600;
    box-shadow: var(--shadow-sm);
  }

  .segment-btn:has(:focus-visible) {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
</style>
