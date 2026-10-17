<script lang="ts">
  import type { BulkArtJobEvent, BulkThemeJobEvent } from "../../generated/ws";
  import DownloadQueue from "./DownloadQueue.svelte";
  import JobCount from "./JobCount.svelte";
  import JobElapsedTime from "./JobElapsedTime.svelte";
  import JobResults from "./JobResults.svelte";
  import JobResultPagination from "./JobResultPagination.svelte";
  import VirtualList from "./VirtualList.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { matchState } from "../stores/matchState.svelte";
  import { themeJobState, type BulkJobState } from "../stores/bulkJobState.svelte";
  import type { DownloadJob } from "../stores/downloadState.svelte";
  import { workflowStatusLabel } from "../utils/assetsPopup";

  // Each workflow's panel appears once its own job has a run, so a panel never
  // stands in for a run that has not been accepted.
  let artStatusLabel = $derived(workflowStatusLabel(matchState));
  let themeStatusLabel = $derived(workflowStatusLabel(themeJobState));
  let artDownloads = $derived(downloadState.activeJobsByType("art"));
  let themeDownloads = $derived(downloadState.activeJobsByType("theme"));
</script>

{#snippet stats(
  state: BulkJobState<BulkArtJobEvent | BulkThemeJobEvent>,
  downloads: DownloadJob[],
  unit: string,
)}
  <div class="stats-row">
    <JobCount job={state} {unit} />
    <div class="stat-item" title="Downloads started">
      queued: <span class="stat-value">{state.counters.queued}</span>
    </div>
    <div class="stat-item" title="Files written to disk">
      downloaded: <span class="stat-value">{state.counters.downloaded}</span>
    </div>
    <div class="stat-item" title="Identical file already on disk; choice saved, nothing downloaded">
      adopted: <span class="stat-value">{state.counters.adopted}</span>
    </div>
    <div class="stat-item">
      skipped: <span class="stat-value">{state.counters.skipped}</span>
    </div>
    <div class="stat-item">
      no match: <span class="stat-value">{state.counters.no_match}</span>
    </div>
    <div class="stat-item">
      errors: <span class="stat-value text-danger">{state.errors}</span>
    </div>
    {#if state.counters.queued > 0}
      <div class="stat-item" title="Queued downloads that have finished, failed or been cancelled">
        downloads settled: <span class="stat-value"
          >{state.counters.settled}/{state.counters.queued}</span
        >
      </div>
    {/if}
    <JobElapsedTime startedAt={state.started_at} finishedAt={state.finished_at} />
  </div>
  <DownloadQueue jobs={downloads} />
{/snippet}

{#snippet artStats()}
  {@render stats(matchState, artDownloads, "slots")}
{/snippet}

{#snippet themeStats()}
  {@render stats(themeJobState, themeDownloads, "items")}
{/snippet}

<div class="asset-results">
  {#if matchState.hasRun}
    <div class="job-panel">
      <div class="job-panel-title">
        <span>Art</span>
        <span class="badge badge-muted">{artStatusLabel}</span>
      </div>
      <JobResults progress={matchState.progress} log={matchState.log} stats={artStats}>
        {#if matchState.results.length > 0}
          <VirtualList
            width="100%"
            maxHeight="min(16vh, 256px)"
            itemCount={matchState.results.length}
            itemSize={32}
            overscanCount={3}
            followEnd
          >
            {#snippet row(index: number, style: string)}
              {@const result = matchState.results[index]}
              {#if result}
                <div class="result-item" {style}>
                  <span class="result-title truncate">{result.title}</span>
                  <span class="badge badge-muted">{result.art_type}</span>
                  {#if result.adopted}
                    <span class="badge badge-success">Adopted</span>
                  {/if}
                  {#if result.perfect_match}
                    <span class="badge badge-success">Perfect match</span>
                  {:else if typeof result.hamming === "number"}
                    <span class="badge badge-accent">d={result.hamming}</span>
                  {:else}
                    <span class="badge badge-success">Catalog</span>
                  {/if}
                  {#if result.source}
                    <span class="badge badge-muted">{result.source}</span>
                  {/if}
                  {#if result.width && result.height}
                    <span class="badge badge-muted">{result.width}x{result.height}</span>
                  {/if}
                </div>
              {/if}
            {/snippet}
          </VirtualList>
        {/if}
        <JobResultPagination page={matchState.page} running={matchState.running} />
      </JobResults>
    </div>
  {/if}

  {#if themeJobState.hasRun}
    <div class="job-panel">
      <div class="job-panel-title">
        <span>Themes</span>
        <span class="badge badge-muted">{themeStatusLabel}</span>
      </div>
      <JobResults progress={themeJobState.progress} log={themeJobState.log} stats={themeStats} />
    </div>
  {/if}
</div>

<style>
  .asset-results {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    min-height: 0;
  }

  .job-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    flex: 0 1 auto;
    min-height: 0;
  }

  .job-panel-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--text-sm);
    font-weight: 700;
    color: var(--text-primary);
  }

  .result-item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-xs);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
    border-bottom: var(--space-1) solid var(--bg-primary);
    box-sizing: border-box;
  }

  .result-title {
    flex: 1;
    min-width: 0;
  }
</style>
