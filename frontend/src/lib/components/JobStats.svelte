<script lang="ts" module>
  /** One figure a run reports beside its progress. */
  export interface JobStat {
    label: string;
    value: number;
    /** What the figure counts, when the label alone does not say. */
    title?: string;
    tone?: "info" | "accent" | "danger" | "success" | "warning" | "violet";
  }

  /** The progress and timing every run reports. */
  export interface JobProgressView {
    planning: boolean;
    done: number;
    total: number | null;
    started_at: string | null;
    finished_at: string | null;
  }
</script>

<script lang="ts">
  import { serverClock } from "../realtime/serverClock";
  import { formatElapsedTime } from "../utils/jobTime";

  let {
    job,
    unit,
    stats,
  }: {
    job: JobProgressView;
    /** What the run counts, such as "items" or "folders". */
    unit: string;
    stats: JobStat[];
  } = $props();

  // Both ends come from the server's clock, so a run counts from 0s and its
  // final time continues from the last running value.
  let elapsed = $derived(
    job.started_at ? formatElapsedTime(job.started_at, job.finished_at || serverClock.now) : "",
  );
</script>

<!-- Each cell is as wide as its label and the widest figure it may show, so
     a figure gaining digits, or a run starting or ending, never moves another
     figure or rewraps the row: only the row's width decides where it wraps. -->
<dl class="job-stats">
  <div class="stat" style:min-width="{unit.length + 15}ch">
    <dt class="sr-only">Progress</dt>
    <dd>
      {#if job.planning}
        Planning...
      {:else}
        <span class="stat-value">{job.done}</span>/{job.total ?? 0} {unit}
      {/if}
    </dd>
  </div>
  {#each stats as stat (stat.label)}
    <div class="stat" title={stat.title} style:min-width="{stat.label.length + 8}ch">
      <dt>{stat.label}:</dt>
      <dd class={["stat-value", stat.tone && `text-${stat.tone}`]}>{stat.value}</dd>
    </div>
  {/each}
  <div class="stat elapsed" style:min-width="22ch">
    <dt>time taken:</dt>
    <dd class="stat-value">{elapsed || "-"}</dd>
  </div>
</dl>

<style>
  .job-stats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    flex: none;
  }

  .stat {
    display: flex;
    align-items: baseline;
    gap: var(--space-1);
    white-space: nowrap;
  }

  .elapsed {
    margin-left: auto;
  }

  dd {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .stat-value {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary);
  }

  .stat-value.text-info {
    color: var(--info);
  }

  .stat-value.text-accent {
    color: var(--accent);
  }

  .stat-value.text-danger {
    color: var(--danger);
  }

  .stat-value.text-success {
    color: var(--success);
  }

  .stat-value.text-warning {
    color: var(--warning);
  }

  .stat-value.text-violet {
    color: var(--violet);
  }
</style>
