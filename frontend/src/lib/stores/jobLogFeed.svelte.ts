import { SvelteMap, SvelteSet } from "svelte/reactivity";
import { getJobLog } from "../../generated/rest/sdk.gen";
import type { JobLogEntry, JobOutcome } from "../../generated/ws";
import { sdkData } from "../rest/sdk";
import { errorMessage } from "../utils/errors";
import { OUTCOMES, OUTCOME_TONES } from "../utils/jobLog";
import type { ResultGroup } from "../utils/resultGroups";

/** Lines fetched per request. */
const PAGE_SIZE = 200;
/** Lines kept on each side of the visible ones; farther ones are fetched again when needed. */
const KEEP = 1000;

/** The log fields every job event may carry. */
export interface JobLogEvent {
  run_id?: string | null;
  log_total?: number | null;
  log_outcomes?: Partial<Record<JobOutcome, number>> | null;
  log?: JobLogEntry | null;
}

/**
 * One run's progress log.
 *
 * The whole log is stored with the run, so a view lists `total` lines and
 * holds only those near what it shows: live lines arrive numbered with the
 * run's events, and the rest are paged in as they scroll into view. A job
 * that is not persisted numbers its live lines itself.
 *
 * Hiding outcomes lists only the other lines: `total` and the positions in
 * `lines` then count among those, and the server pages them filtered.
 */
export class JobLogFeed {
  runId = $state<string | null>(null);
  /** Lines listed: every line of the run, or those the filter shows. */
  total = $state(0);
  error = $state("");
  readonly lines = new SvelteMap<number, JobLogEntry>();
  /** Outcomes whose lines are hidden. */
  readonly hidden = new SvelteSet<JobOutcome>();
  /** The run's lines per outcome, as its latest event counts them. */
  counts = $state<Partial<Record<JobOutcome, number>>>({});
  private view: readonly [number, number] = [0, 0];
  /** The requests in flight, by page. */
  private readonly loading = new SvelteMap<number, AbortController>();
  /** Every line of the run, shown or hidden. */
  private logTotal = 0;

  /** Each outcome the run has logged, with its count, for the log's filters. */
  get groups(): ResultGroup<JobOutcome>[] {
    if (!this.runId) return [];
    return OUTCOMES.filter((outcome) => this.counts[outcome]).map((outcome) => ({
      key: outcome,
      label: outcome,
      count: this.counts[outcome] ?? 0,
      shown: !this.hidden.has(outcome),
      tone: OUTCOME_TONES[outcome],
    }));
  }

  /** Take the line an event adds, and follow the run it names. */
  apply(event: JobLogEvent) {
    if (event.run_id && event.run_id !== this.runId) {
      this.reset();
      this.runId = event.run_id;
    }
    if (event.log_outcomes) this.counts = event.log_outcomes;
    this.logTotal = Math.max(
      this.logTotal,
      event.log_total ?? (event.log ? this.logTotal + 1 : this.logTotal),
    );
    if (this.hidden.size) {
      // The counts include the line this event adds, so it is the last shown.
      this.total = this.listed();
      if (event.log && !this.hidden.has(event.log.outcome)) {
        this.lines.set(this.total - 1, event.log);
      }
    } else {
      if (event.log) this.lines.set(this.logTotal - 1, event.log);
      this.total = Math.max(this.total, this.logTotal);
    }
    if (this.lines.size > 3 * KEEP) this.evict();
  }

  /** Show an outcome's lines again, or hide them, and list the lines anew. */
  toggleOutcome(outcome: JobOutcome) {
    if (!this.hidden.delete(outcome)) this.hidden.add(outcome);
    this.abortLoads();
    this.lines.clear();
    this.error = "";
    this.total = this.hidden.size ? this.listed() : this.logTotal;
    const [first, end] = this.view;
    const from = Math.max(0, Math.min(first, this.total - (end - first)));
    this.show(from, from + (end - first));
  }

  /** The lines the filter shows, by the run's counts. */
  private listed(): number {
    return OUTCOMES.reduce(
      (sum, outcome) => (this.hidden.has(outcome) ? sum : sum + (this.counts[outcome] ?? 0)),
      0,
    );
  }

  /** Lines `first` up to `end` are on screen: fetch those not held, drop far ones. */
  show(first: number, end: number) {
    this.view = [first, end];
    this.evict();
    const runId = this.runId;
    if (!runId) return;
    for (let page = Math.floor(first / PAGE_SIZE); page * PAGE_SIZE < end; page++) {
      const from = Math.max(first, page * PAGE_SIZE);
      const to = Math.min(end, (page + 1) * PAGE_SIZE);
      if (this.loading.has(page) || this.holds(from, to)) continue;
      void this.load(runId, page);
    }
  }

  /** Fetch the lines on screen again after a failed request. */
  retry() {
    this.error = "";
    this.show(...this.view);
  }

  reset() {
    this.abortLoads();
    this.lines.clear();
    this.hidden.clear();
    this.runId = null;
    this.total = 0;
    this.logTotal = 0;
    this.counts = {};
    this.error = "";
    this.view = [0, 0];
  }

  private abortLoads() {
    for (const request of this.loading.values()) request.abort();
    this.loading.clear();
  }

  private holds(from: number, to: number): boolean {
    for (let ordinal = from; ordinal < to; ordinal++) {
      if (!this.lines.has(ordinal)) return false;
    }
    return true;
  }

  private evict() {
    const [first, end] = this.view;
    for (const ordinal of this.lines.keys()) {
      if (ordinal < first - KEEP || ordinal >= end + KEEP) this.lines.delete(ordinal);
    }
  }

  private async load(runId: string, page: number) {
    const request = new AbortController();
    this.loading.set(page, request);
    const outcome = this.hidden.size
      ? OUTCOMES.filter((shown) => !this.hidden.has(shown))
      : undefined;
    try {
      const result = await sdkData(
        getJobLog({
          path: { run_id: runId },
          query: { offset: page * PAGE_SIZE, limit: PAGE_SIZE, outcome },
          signal: request.signal,
          throwOnError: true,
        }),
      );
      if (this.runId !== runId || request.signal.aborted) return;
      result.items.forEach((entry, index) => {
        const ordinal = result.offset + index;
        if (!this.lines.has(ordinal)) this.lines.set(ordinal, entry);
      });
      this.total = Math.max(this.total, result.total);
    } catch (error) {
      if (!request.signal.aborted && this.runId === runId) {
        this.error = errorMessage(error, "Could not load the log. Please retry.");
      }
    } finally {
      if (this.loading.get(page) === request) this.loading.delete(page);
    }
  }
}
