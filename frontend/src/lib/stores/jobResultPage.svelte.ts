import { getJobResults } from "../../generated/rest/sdk.gen";
import { sdkData } from "../rest/sdk";
import { errorMessage } from "../utils/errors";

export interface ResultPageEvent {
  results_run_id?: string | null;
  results_total?: number | null;
}

/** Owns one bounded result page and cancels requests when the run changes. */
export class JobResultPage<T> {
  readonly size = 100;
  runId = $state<string | null>(null);
  total = $state(0);
  offset = $state(0);
  loading = $state(false);
  error = $state("");
  private request: AbortController | null = null;
  private apply: (items: T[]) => void;

  constructor(apply: (items: T[]) => void) {
    this.apply = apply;
  }

  update(event: ResultPageEvent, terminal = false) {
    const runId = event.results_run_id;
    if (!runId) return;
    const changed = runId !== this.runId;
    if (changed) {
      this.reset();
      this.runId = runId;
      this.apply([]);
    }
    this.total = event.results_total ?? this.total;
    if (changed || terminal) void this.load(this.offset);
  }

  async load(offset = this.offset) {
    if (!this.runId) return;
    this.request?.abort();
    const request = new AbortController();
    this.request = request;
    const runId = this.runId;
    this.loading = true;
    this.error = "";
    try {
      const page = await sdkData(
        getJobResults({
          path: { run_id: runId },
          query: { offset, limit: this.size },
          signal: request.signal,
          throwOnError: true,
        }),
      );
      if (request !== this.request) return;
      this.offset = offset;
      this.total = page.total;
      // Rows are serialized by the same backend models as the typed WS events.
      this.apply(page.items as T[]);
    } catch (error) {
      if (request === this.request && !request.signal.aborted) {
        this.error = errorMessage(error, "Could not load results. Please retry.");
      }
    } finally {
      if (request === this.request) this.loading = false;
    }
  }

  reset() {
    this.request?.abort();
    this.request = null;
    this.runId = null;
    this.offset = 0;
    this.total = 0;
    this.loading = false;
    this.error = "";
  }
}
