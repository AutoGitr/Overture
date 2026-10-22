<script lang="ts">
  import type { JobLogFeed } from "../stores/jobLogFeed.svelte";
  import { OUTCOME_TONES, logEntryTime } from "../utils/jobLog";
  import ResultFilters from "./ResultFilters.svelte";
  import VirtualList from "./VirtualList.svelte";

  let {
    feed,
    filling = false,
  }: {
    feed: JobLogFeed;
    /** A running log asks for all the room it may get at once, so it never grows line by line. */
    filling?: boolean;
  } = $props();

  const ROW_HEIGHT = 24;
</script>

<!-- A region of the panel that asks for its lines' height; the popup gives
     it what the screen allows, down to three lines, and it scrolls past
     that. Lines load and arrive without moving anything around it. -->
<ResultFilters
  label="Show log lines by outcome"
  groups={feed.groups}
  ontoggle={(outcome) => feed.toggleOutcome(outcome)}
/>
<div
  class="job-log"
  role="log"
  aria-label="Job log"
  style:--log-rows-height={filling ? "100dvh" : `${Math.max(feed.total, 3) * ROW_HEIGHT}px`}
>
  {#if feed.total > 0}
    <VirtualList
      itemCount={feed.total}
      itemSize={ROW_HEIGHT}
      overscanCount={10}
      followEnd
      onVisibleRangeChange={(first, end) => feed.show(first, end)}
    >
      {#snippet row(index: number, style: string)}
        {@const entry = feed.lines.get(index)}
        {#if entry}
          <div class="job-log-row" {style} title="{entry.target} - {entry.reason}">
            <time class="log-time" datetime={entry.at}>{logEntryTime(entry)}</time>
            <span class="log-outcome {OUTCOME_TONES[entry.outcome]}">{entry.outcome}</span>
            <span class="log-target">{entry.target}</span>
            <span class="log-reason">{entry.reason}</span>
          </div>
        {:else}
          <div class="job-log-row" {style} aria-hidden="true">
            <span class="log-placeholder"></span>
          </div>
        {/if}
      {/snippet}
    </VirtualList>
  {:else}
    <span class="log-empty">
      {feed.hidden.size ? "No lines match the filters above" : "Nothing logged yet"}
    </span>
  {/if}
  {#if feed.error}
    <div class="log-error" role="alert">
      <span>{feed.error}</span>
      <button type="button" class="btn btn-ghost btn-sm" onclick={() => feed.retry()}>Retry</button>
    </div>
  {/if}
</div>

<style>
  /* Its height is the room its grid row gets: the strut below is the height
     it asks for and three lines are the least it takes. The rows, empty
     text and error share the strut's cell. */
  .job-log {
    position: relative;
    display: grid;
    grid-template: minmax(0, 1fr) / minmax(0, 1fr);
    box-sizing: content-box;
    min-height: calc(3 * 24px);
    padding: var(--space-2) var(--space-3);
    background: var(--bg-root);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    line-height: 1.7;
    overflow: hidden;
  }

  .job-log::before {
    content: "";
    grid-area: 1 / 1;
    height: var(--log-rows-height);
  }

  .job-log > :global(*) {
    grid-area: 1 / 1;
  }

  .job-log-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    padding: 0 var(--space-1);
    box-sizing: border-box;
    white-space: nowrap;
  }

  .log-time {
    flex: none;
    color: var(--text-tertiary);
    font-variant-numeric: tabular-nums;
  }

  .log-outcome {
    flex: none;
    min-width: 10ch;
    padding: 0 var(--space-1);
    border-radius: var(--radius-sm);
    font-weight: 600;
    line-height: 18px;
    text-align: center;
  }

  .log-outcome.info {
    color: var(--info);
    background: var(--info-muted);
  }

  .log-outcome.success {
    color: var(--success);
    background: var(--success-muted);
  }

  .log-outcome.warning {
    color: var(--warning);
    background: var(--warning-muted);
  }

  .log-outcome.danger {
    color: var(--danger);
    background: var(--danger-muted);
  }

  .log-outcome.muted {
    color: var(--text-tertiary);
    background: var(--badge-muted-bg);
  }

  .log-target,
  .log-reason {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .log-target {
    flex: 0 1 auto;
    max-width: 50%;
    color: var(--text-primary);
  }

  .log-reason {
    flex: 1 1 0;
    color: var(--text-secondary);
  }

  .log-placeholder {
    flex: 1;
    height: 8px;
    border-radius: var(--radius-full);
    background: var(--badge-muted-bg);
  }

  .log-empty {
    margin: auto;
    color: var(--text-tertiary);
    font-family: var(--font-sans);
  }

  .log-error {
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
    font-family: var(--font-sans);
    box-shadow: var(--shadow-md);
  }
</style>
