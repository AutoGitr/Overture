<script lang="ts">
  import type { Snippet } from "svelte";
  import CheckCheck from "@lucide/svelte/icons/check-check";
  import ResultFilters from "./ResultFilters.svelte";
  import VirtualList from "./VirtualList.svelte";
  import type { ResultGroup } from "../utils/resultGroups";

  let {
    itemCount,
    total,
    itemSize,
    noun,
    subtitle,
    emptyLabel,
    showEmpty,
    selectedCount,
    hiddenSelectedCount,
    actionableCount,
    groups,
    running,
    findings,
    onSelectAll,
    onToggleGroup,
    row,
  }: {
    /** Findings shown; `row` receives positions among them. */
    itemCount: number;
    /** Every finding of the run, shown or hidden. */
    total: number;
    itemSize: number;
    /** What a finding is called, in the plural. */
    noun: string;
    subtitle: string;
    emptyLabel: string;
    showEmpty: boolean;
    /** Shown findings that are selected. */
    selectedCount: number;
    /** Checked findings that are hidden, and so left out of every action. */
    hiddenSelectedCount: number;
    /** Shown findings that can be selected. */
    actionableCount: number;
    /** The kinds findings are shown or hidden by. */
    groups: readonly ResultGroup[];
    running: boolean;
    /** Fetching the run's stored findings, and how it went. */
    findings: { loading: boolean; loadError: string; retry: () => void };
    /** Select or clear every shown finding. */
    onSelectAll: (checked: boolean) => void;
    onToggleGroup: (key: string) => void;
    row: Snippet<[number, string]>;
  } = $props();

  let allSelected = $derived(actionableCount > 0 && selectedCount === actionableCount);
</script>

<!-- A region of its job panel, as tall as its rows up to a bound, past which
     it scrolls: findings arriving never push or squeeze what is around it
     beyond that bound. -->
<div class="findings">
  <div class="findings-header">
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={allSelected}
        indeterminate={selectedCount > 0 && !allSelected}
        disabled={running || actionableCount === 0}
        aria-label="Select every shown {noun}"
        onchange={(event) => onSelectAll(event.currentTarget.checked)}
      />
      <span class="font-semibold">
        {itemCount === total ? `${total} ${noun}` : `${itemCount} of ${total} ${noun} shown`}
      </span>
    </label>
    <span class="findings-subtitle">
      {subtitle}
      {#if hiddenSelectedCount > 0}
        <span class="hidden-selected">
          &middot; {hiddenSelectedCount} more checked but hidden, so left out
        </span>
      {/if}
    </span>
  </div>
  <ResultFilters label="Show {noun} by kind" {groups} ontoggle={onToggleGroup} />
  {#if itemCount > 0}
    <div class="findings-list" style:--findings-rows-height="{itemCount * itemSize}px">
      <VirtualList {itemCount} {itemSize} overscanCount={3} followEnd={running} {row} />
    </div>
  {:else}
    <div class="findings-empty">
      {#if findings.loading}
        <span>Loading results...</span>
      {:else if total > 0}
        <span>All {noun} are hidden by the filters above.</span>
      {:else if showEmpty && !findings.loadError}
        <CheckCheck size={20} />
        <span>{emptyLabel}</span>
      {:else if !findings.loadError}
        <span>Nothing found yet</span>
      {/if}
    </div>
  {/if}
  {#if findings.loadError}
    <div class="findings-error" role="alert">
      <span>{findings.loadError}</span>
      <button type="button" class="btn btn-ghost btn-sm" onclick={findings.retry}>Retry</button>
    </div>
  {/if}
</div>

<style>
  .findings {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    flex: none;
  }

  .findings-error {
    position: absolute;
    inset: auto var(--space-2) var(--space-2);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--bg-elevated);
    color: var(--danger);
    font-size: var(--text-xs);
    box-shadow: var(--shadow-md);
  }

  .findings-header {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    min-height: 28px;
  }

  .findings-subtitle {
    margin-left: auto;
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  /* As tall as the rows, but never taller than about half the screen. */
  .hidden-selected {
    color: var(--warning);
  }

  .findings-list {
    display: flex;
    flex-direction: column;
    height: min(var(--findings-rows-height), max(18rem, 45dvh));
    border-top: var(--border-subtle);
  }

  .findings-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    min-height: 6rem;
    border-top: var(--border-subtle);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    text-align: center;
  }
</style>
