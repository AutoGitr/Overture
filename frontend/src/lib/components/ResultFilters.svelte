<script lang="ts" generics="K extends string">
  import type { ResultGroup } from "../utils/resultGroups";

  let {
    groups,
    label,
    ontoggle,
  }: {
    groups: readonly ResultGroup<K>[];
    /** Names the set of filters for assistive technology. */
    label: string;
    ontoggle: (key: K) => void;
  } = $props();
</script>

<!-- Each kind of result, with how many there are, shown or hidden in one
     press; nothing until there is a first result. -->
{#if groups.length > 0}
  <div class="result-filters" role="group" aria-label={label}>
    {#each groups as group (group.key)}
      <button
        type="button"
        class={["result-filter", group.tone]}
        aria-pressed={group.shown}
        title={group.shown ? `Hide ${group.label}` : `Show ${group.label}`}
        onclick={() => ontoggle(group.key)}
      >
        <span class="result-label">{group.label}</span>
        <span class="result-count">{group.count}</span>
      </button>
    {/each}
  </div>
{/if}

<style>
  .result-filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    min-width: 0;
  }

  .result-filter {
    --filter-colour: var(--text-secondary);
    --filter-bg: var(--bg-secondary);

    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    max-width: 100%;
    padding: 2px var(--space-2);
    border: var(--border-subtle);
    border-radius: var(--radius-full);
    background: var(--filter-bg);
    color: var(--filter-colour);
    font-size: var(--text-xs);
    font-weight: 500;
  }

  .result-filter.info {
    --filter-colour: var(--info);
    --filter-bg: var(--info-muted);
  }

  .result-filter.success {
    --filter-colour: var(--success);
    --filter-bg: var(--success-muted);
  }

  .result-filter.warning {
    --filter-colour: var(--warning);
    --filter-bg: var(--warning-muted);
  }

  .result-filter.danger {
    --filter-colour: var(--danger);
    --filter-bg: var(--danger-muted);
  }

  .result-filter.muted {
    --filter-colour: var(--text-tertiary);
    --filter-bg: var(--badge-muted-bg);
  }

  .result-filter:hover {
    border-color: var(--filter-colour);
  }

  /* A hidden kind keeps its place and count, struck through and faded. */
  .result-filter[aria-pressed="false"] {
    background: transparent;
    color: var(--text-tertiary);
    opacity: 0.7;
  }

  .result-filter[aria-pressed="false"] .result-label {
    text-decoration: line-through;
  }

  .result-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .result-count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    opacity: 0.8;
  }
</style>
