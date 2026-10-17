<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { DownloadJob } from "../stores/downloadState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";

  let { jobs }: { jobs: DownloadJob[] } = $props();
</script>

{#if downloadState.loadingPending}
  <span class="text-muted" role="status">Loading queued downloads...</span>
{:else if downloadState.pendingError}
  <div role="alert">
    <span class="text-danger">{downloadState.pendingError}</span>
    <button class="btn btn-ghost" onclick={() => downloadState.loadPending()}>Retry</button>
  </div>
{/if}

{#if jobs.length > 0}
  <div class="download-queue">
    {#each jobs as job (job.job_id)}
      <div class="download-row">
        <LoaderCircle size={12} class="animate-spin" />
        <span class="download-title truncate">{job.title || "Queued download"}</span>
        {#if job.art_type}
          <span class="badge badge-muted">{job.art_type}</span>
        {/if}
        <span class="download-stage">{job.stage}</span>
        <div class="progress-bar download-bar progress-bar-sm">
          <div class="progress-bar-fill" style="width:{job.percent}%"></div>
        </div>
        <span class="download-percent">{Math.round(job.percent)}%</span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .download-queue {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .download-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border-radius: var(--radius-sm);
  }

  .download-title {
    flex: 1;
    min-width: 0;
    color: var(--text-primary);
  }

  .download-bar {
    flex: none;
    width: 80px;
  }

  .download-percent {
    width: 34px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
</style>
