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
    /**
     * The run's findings: exactly two elements, a fixed head and a list that
     * shares the room the popup gives with the log, like `JobResultsList`.
     */
    children?: Snippet;
  } = $props();

  let running = $derived(Boolean(job.started_at && !job.finished_at));
</script>

<!-- One run's results: its rows are rows of the grid that holds every run
     shown, so the lists of all of them share the popup's room, each asking
     for its own height and getting its share of what the screen allows. -->
<section class="job-panel" aria-label={title} style:grid-row="span {children ? 5 : 3}">
  <div class="job-panel-top">
    {#if title}
      <header class="job-panel-header">
        <h3>{title}</h3>
        {#if status}
          <span class="badge badge-muted">{status}</span>
        {/if}
      </header>
    {/if}
    <div
      class={["progress-bar", { active: running }]}
      role="progressbar"
      aria-valuenow={Math.round(job.progress)}
    >
      <div class="progress-bar-fill" style:width="{job.progress}%"></div>
    </div>
    <JobStats {job} {unit} {stats} />
    {@render sections?.()}
  </div>
  {@render children?.()}
  <JobLog feed={job.log} filling={running} />
</section>

<style>
  .job-panel {
    display: grid;
    grid-template-rows: subgrid;
    row-gap: var(--space-3);
    min-width: 0;
    padding: var(--space-3);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
    box-shadow: inset 3px 0 0 var(--job-accent, var(--accent));
  }

  .job-panel-top {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
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
    color: var(--job-accent, var(--text-primary));
  }
</style>
