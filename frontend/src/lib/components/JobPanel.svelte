<script lang="ts">
  import type { Snippet } from "svelte";
  import type { JobLogFeed } from "../stores/jobLogFeed.svelte";
  import JobLog from "./JobLog.svelte";
  import JobStats, { type JobProgressView, type JobStat } from "./JobStats.svelte";

  let {
    job,
    unit,
    stats,
    title,
    status,
    sections,
    children,
  }: {
    job: JobProgressView & { progress: number; log: JobLogFeed };
    unit: string;
    stats: JobStat[];
    /** Names the run when a view shows more than one. */
    title?: string;
    status?: string;
    /** Fixed-height parts shown above the lists, such as running downloads. */
    sections?: Snippet;
    /** The run's findings, a region that shares the panel's height with its log. */
    children?: Snippet;
  } = $props();
</script>

<!-- One run's results, every part as tall as its content up to its own bound,
     so no part squeezes or covers another; the popup's body scrolls past
     them when the screen is shorter. -->
<section class="job-panel" aria-label={title}>
  {#if title}
    <header class="job-panel-header">
      <h3>{title}</h3>
      {#if status}
        <span class="badge badge-muted">{status}</span>
      {/if}
    </header>
  {/if}
  <div
    class={["progress-bar", { active: Boolean(job.started_at && !job.finished_at) }]}
    role="progressbar"
    aria-valuenow={Math.round(job.progress)}
  >
    <div class="progress-bar-fill" style:width="{job.progress}%"></div>
  </div>
  <JobStats {job} {unit} {stats} />
  {@render sections?.()}
  {@render children?.()}
  <JobLog feed={job.log} />
</section>

<style>
  .job-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
    padding: var(--space-3);
    border: var(--border-subtle);
    border-top: 2px solid var(--job-accent, var(--accent));
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
  }

  .job-panel .progress-bar-fill {
    background: var(--job-accent, var(--accent));
  }

  .job-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-height: 24px;
  }

  h3 {
    font-size: var(--text-sm);
    font-weight: 700;
    color: var(--text-primary);
  }
</style>
