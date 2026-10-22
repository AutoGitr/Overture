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

<!-- Two rows of its job panel: a fixed head, and a list that asks for its
     rows' height (all the room it may get while running, so it never grows
     row by row) and takes what the popup gives, past which it scrolls. -->
<div class="findings-head">
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
</div>
<div
  class="findings-body"
  style:--findings-rows-height={running ? "100dvh" : `${itemCount * itemSize}px`}
>
  {#if itemCount > 0}
    <VirtualList {itemCount} {itemSize} overscanCount={3} followEnd={running} {row} />
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
  .findings-head {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
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

  .hidden-selected {
    color: var(--warning);
  }

  /* Its height is the room its grid row gets: the strut below is the height
     it asks for and six rem the least it takes. The rows, empty text and
     error share the strut's cell. */
  .findings-body {
    position: relative;
    display: grid;
    grid-template: minmax(0, 1fr) / minmax(0, 1fr);
    min-height: 6rem;
    border-top: var(--border-subtle);
  }

  .findings-body::before {
    content: "";
    grid-area: 1 / 1;
    height: var(--findings-rows-height);
  }

  .findings-body > :global(*) {
    grid-area: 1 / 1;
  }

  .findings-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    text-align: center;
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
</style>
