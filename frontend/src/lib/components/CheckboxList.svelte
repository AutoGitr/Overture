<script lang="ts" generics="T extends string">
  let {
    options,
    selected,
    ontoggle,
  }: {
    options: readonly { value: T; label: string; count?: number }[];
    selected: readonly T[];
    ontoggle: (value: T) => void;
  } = $props();
</script>

<div class="list">
  {#each options as option (option.value)}
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={selected.includes(option.value)}
        onchange={() => ontoggle(option.value)}
      />
      <span class="label">
        {option.label}
        {#if option.count !== undefined}
          <span class="count">{option.count}</span>
        {/if}
      </span>
    </label>
  {/each}
</div>

<style>
  /* Columns as many as fit, so options wrap only when the row is full. */
  .list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 11rem), 1fr));
    gap: var(--space-2) var(--space-4);
  }

  .label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
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
