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
    /** The saved schedule that started the run; `null` when started by hand. */
    schedule: string | null;
  }
</script>

<script lang="ts">
  import { serverClock } from "../realtime/serverClock";
  import { elapsedSeconds } from "../utils/jobTime";
  import { formatDuration } from "../utils/popupFormat";

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

  // The shown time never runs backwards: a clock resync or a finished_at a
  // little behind the live clock keeps what was already counted.
  let maxSeconds = $state(0);
  let activeStart = $state<string | null>(null);

  let currentSeconds = $derived(
    job.started_at ? elapsedSeconds(job.started_at, job.finished_at || serverClock.now) : 0,
  );

  $effect(() => {
    if (job.started_at !== activeStart) {
      activeStart = job.started_at;
      maxSeconds = currentSeconds;
    } else if (currentSeconds > maxSeconds) {
      maxSeconds = currentSeconds;
    }
  });

  let elapsed = $derived(
    job.started_at ? formatDuration(Math.max(currentSeconds, maxSeconds)) : "",
  );
</script>

<!-- Each figure sits under its label and keeps room for as many digits as
     the run's total has, so a figure gaining digits, or a run starting or
     ending, never moves another figure: only the row's width decides where
     it wraps. -->
<dl class="job-stats" style:--digits={String(job.total ?? 0).length}>
  <div class="stat">
    <dt>{unit}</dt>
    <dd class="stat-value progress">
      {#if job.planning}
        Planning...
      {:else}
        {job.done}<span class="stat-total">/{job.total ?? 0}</span>
      {/if}
    </dd>
  </div>
  {#each stats as stat (stat.label)}
    <div class="stat" title={stat.title}>
      <dt>{stat.label}</dt>
      <dd class={["stat-value", stat.tone && `text-${stat.tone}`]}>{stat.value}</dd>
    </div>
  {/each}
  <div
    class="stat elapsed"
    title={job.schedule ? `Started by the schedule ${job.schedule}` : undefined}
  >
    <dt>{job.schedule ? `scheduled: ${job.schedule}` : "time"}</dt>
    <dd class="stat-value">{elapsed || "-"}</dd>
  </div>
</dl>

<style>
  .job-stats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-5);
    margin: 0;
    flex: none;
  }

  .stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
    white-space: nowrap;
  }

  dt {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .elapsed {
    margin-left: auto;
    text-align: right;
  }

  dd {
    margin: 0;
  }

  .stat-value {
    min-width: calc(var(--digits) * 1ch);
    font-size: var(--text-sm);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary);
  }

  .stat-value.progress {
    min-width: calc(var(--digits) * 2ch + 1ch);
  }

  .elapsed .stat-value {
    min-width: 8ch;
  }

  .stat-total {
    color: var(--text-tertiary);
    font-weight: 500;
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
