<script lang="ts">
  import type { Snippet } from "svelte";
  import CheckCheck from "@lucide/svelte/icons/check-check";
  import VirtualList from "./VirtualList.svelte";
  import type { SelectionGroup } from "../stores/collectingJobState.svelte";

  let {
    itemCount,
    itemSize,
    heading,
    subtitle,
    emptyLabel,
    showEmpty,
    selectedCount,
    actionableCount,
    groups = [],
    running,
    onSelectAll,
    onToggleGroup,
    row,
  }: {
    itemCount: number;
    itemSize: number;
    heading: string;
    subtitle: string;
    emptyLabel: string;
    showEmpty: boolean;
    selectedCount: number;
    actionableCount: number;
    /** Kinds of findings that can be selected together. */
    groups?: SelectionGroup[];
    running: boolean;
    onSelectAll: (checked: boolean) => void;
    onToggleGroup?: (key: string) => void;
    row: Snippet<[number, string]>;
  } = $props();

  let allSelected = $derived(actionableCount > 0 && selectedCount === actionableCount);
</script>

{#if itemCount > 0}
  <div class="issues-header">
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={allSelected}
        indeterminate={selectedCount > 0 && !allSelected}
        disabled={running || actionableCount === 0}
        onchange={(event) => onSelectAll(event.currentTarget.checked)}
      />
      <span class="font-semibold">{heading}</span>
    </label>
    <span class="issues-subtitle">{subtitle}</span>
  </div>
  {#if !running && groups.length > 1}
    <div class="selection-groups" role="group" aria-label="Select by kind">
      {#each groups as group (group.key)}
        <button
          type="button"
          class="selection-group"
          class:partial={group.selected > 0 && group.selected < group.total}
          aria-pressed={group.selected === group.total}
          title={group.selected === group.total
            ? `Clear every ${group.label} result`
            : `Select every ${group.label} result`}
          onclick={() => onToggleGroup?.(group.key)}
        >
          {group.label}
          <span class="selection-count">{group.selected}/{group.total}</span>
        </button>
      {/each}
    </div>
  {/if}
  <div class="issues-list">
    <VirtualList
      width="100%"
      maxHeight="min(38vh, 456px)"
      {itemCount}
      {itemSize}
      overscanCount={3}
      followEnd={running}
      {row}
    />
  </div>
{:else if showEmpty}
  <div class="no-issues">
    <CheckCheck size={20} />
    <span>{emptyLabel}</span>
  </div>
{/if}

<style>
  .selection-groups {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    padding: var(--space-2) 0;
  }
  .selection-group {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 2px var(--space-2);
    border: var(--border-subtle);
    border-radius: var(--radius-full);
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: var(--text-xs);
  }
  .selection-group:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .selection-group[aria-pressed="true"] {
    background: var(--accent-muted);
    border-color: var(--accent-border);
    color: var(--accent);
  }
  .selection-group.partial {
    border-color: var(--accent-border);
  }
  .selection-count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    opacity: 0.75;
  }
</style>
