<script lang="ts" generics="T extends string">
  let {
    options,
    selected,
    ontoggle,
  }: {
    /** A `disabled` option shows its state but cannot be toggled; `title` says why. */
    options: readonly {
      value: T;
      label: string;
      count?: number;
      disabled?: boolean;
      title?: string;
    }[];
    selected: readonly T[];
    ontoggle: (value: T) => void;
  } = $props();
  let selectedSet = $derived<ReadonlySet<T>>(new Set(selected));
</script>

<div class="list">
  {#each options as option (option.value)}
    <span class="option">
      <label class="checkbox-group" title={option.title}>
        <input
          type="checkbox"
          checked={selectedSet.has(option.value)}
          disabled={option.disabled}
          onchange={() => ontoggle(option.value)}
        />
        <span class="label">{option.label}</span>
      </label>
      {#if option.count !== undefined}
        <span class="count">{option.count}</span>
      {/if}
    </span>
  {/each}
</div>

<style>
  /* Each option is as wide as its label, so short ones sit close and the row
     wraps only when it is full. */
  .list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
  }

  .option {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-2);
    min-width: 0;
  }

  .label {
    min-width: 0;
    overflow-wrap: anywhere;
    color: var(--text-secondary);
  }

  .count {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    font-family: var(--font-mono);
  }
</style>
