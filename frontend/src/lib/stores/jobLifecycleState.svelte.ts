import type { JobOutcome } from "../../generated/ws";
import { serverClock } from "../realtime/serverClock";
import { jobEventErrorMessage } from "../utils/errors";
import { JobLogFeed, type JobLogEvent } from "./jobLogFeed.svelte";

export type JobStatus = "idle" | "running" | "completed" | "stopped" | "failed";

export interface JobLifecycleEvent extends JobLogEvent {
  job?: { id?: string | null; error?: { message?: string | null } | null } | null;
  done?: number | null;
  total?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  schedule?: string | null;
}

/** How one job's events are read. */
export interface JobLifecycleConfig {
  /** Message shown when the job fails without one. */
  failureMessage: string;
}

/**
 * One background job as its realtime events describe it.
 *
 * Every job publishes the same lifecycle (started, progress, completed,
 * stopped, failed), so the handlers live here; a job that also collects
 * findings extends this class. What the run did is counted from its log
 * alone (`count`), so the figures always match the log's filters.
 */
export class JobLifecycleState<T extends JobLifecycleEvent> {
  status = $state<JobStatus>("idle");
  done = $state(0);
  /** Every target the run will report on; `null` until the run has planned them. */
  total = $state<number | null>(null);
  readonly log = new JobLogFeed();
  started_at = $state<string | null>(null);
  finished_at = $state<string | null>(null);
  /** The saved schedule that started the run; `null` when started by hand. */
  schedule = $state<string | null>(null);
  error = $state<string | null>(null);
  /** A stop was accepted and the run has not ended yet. */
  stopping = $state(false);

  protected readonly config: JobLifecycleConfig;

  constructor(config: JobLifecycleConfig) {
    this.config = config;
  }

  /** The targets the run's log reported with `outcome`. */
  count(outcome: JobOutcome): number {
    return this.log.targets[outcome] ?? 0;
  }

  get running(): boolean {
    return this.status === "running";
  }

  /**
   * Whether there is a run to show: one in progress, or what the last one
   * left behind. A job popup shows its results exactly while this holds, so
   * the view follows the job instead of guessing ahead of the server.
   */
  get hasRun(): boolean {
    return this.running || !!this.finished_at || this.log.total > 0 || !!this.total;
  }

  /** Percentage done, unrounded so a long run's bar moves with every item. */
  get progress(): number {
    return this.total ? (this.done / this.total) * 100 : 0;
  }

  /** Whether the run is still building its work list, so its total is unknown. */
  get planning(): boolean {
    return this.running && this.total === null;
  }

  handleStarted(data: T) {
    this.resetLifecycle();
    this.status = "running";
    this.started_at = data.started_at || serverClock.isoNow();
    this.apply(data);
  }

  handleProgress(data: T) {
    this.status = "running";
    this.apply(data);
  }

  handleCompleted(data: T) {
    this.finish("completed", data);
  }

  handleStopped(data: T) {
    this.finish("stopped", data);
  }

  handleFailed(data: T) {
    this.error = jobEventErrorMessage(data, this.config.failureMessage);
    this.finish("failed", data);
  }

  /**
   * Show an accepted start request as running while its first realtime event
   * is on the way. A run's own events may arrive before the request's answer,
   * so only a job that has not reported anything yet is changed.
   */
  markStartAccepted() {
    if (this.status !== "idle") return;
    this.status = "running";
    this.started_at = serverClock.isoNow();
  }

  /** Keep "Stopping" on screen from the accepted stop until the run ends. */
  markStopRequested() {
    if (this.running) this.stopping = true;
  }

  /** Forget everything the job showed, as after a cleared result. */
  reset() {
    this.resetLifecycle();
  }

  /** Forget the lifecycle; a subclass keeps what it collects. */
  protected resetLifecycle() {
    this.status = "idle";
    this.done = 0;
    this.total = null;
    this.log.reset();
    this.started_at = null;
    this.finished_at = null;
    this.schedule = null;
    this.error = null;
    this.stopping = false;
  }

  private finish(status: Exclude<JobStatus, "idle" | "running">, data: T) {
    this.status = status;
    this.apply(data);
    this.finished_at = data.finished_at || serverClock.isoNow();
    this.stopping = false;
    this.log.finish(data);
  }

  /** Copy whichever figures the event carried, keeping the rest. */
  private apply(data: T) {
    this.done = data.done ?? this.done;
    this.total = data.total ?? this.total;
    this.started_at = data.started_at || this.started_at;
    this.schedule = data.schedule ?? this.schedule;
    this.absorb(data);
    this.log.apply(data);
  }

  /** Take what a subclass reads from each event besides the shared figures. */
  protected absorb(_data: T) {}
}
