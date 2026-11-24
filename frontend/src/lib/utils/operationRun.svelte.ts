import type { ClearableJobKind } from "../../generated/ws";
import { libraryGate } from "../stores/libraryGate.svelte";
import { createNotifier } from "../stores/notificationState.svelte";
import { OPERATIONS } from "../stores/operations";
import type { OperationsTab } from "../stores/uiState.svelte";
import { errorMessage } from "./errors";
import { createClearResults } from "./jobSnapshots";

/** What an operation's tab says about a run of it, and how it starts, stops and clears one. */
export class OperationRun {
  readonly feedback = createNotifier();
  readonly clearResults;
  /** A start or stop request is on its way. */
  starting = $state(false);
  #stopRequested = $state(false);

  constructor(
    private readonly tab: OperationsTab,
    private readonly options: {
      /** Why the tab's form cannot start a run, or null when it can. */
      blocker: () => string | null;
      /** The results Clear results removes. */
      results: () => ClearableJobKind[];
      /** Whether one of its jobs is stopping. */
      stopping: () => boolean;
    },
  ) {
    this.clearResults = createClearResults(options.results, this.feedback);
  }

  /** Why a run cannot start now: another operation running, else the form. */
  readonly blocked = $derived.by(() => libraryGate.blocked(this.tab) ?? this.options.blocker());

  /** A run exists, so its results show instead of the form. */
  get hasResults(): boolean {
    return OPERATIONS[this.tab].hasRun;
  }

  get running(): boolean {
    return OPERATIONS[this.tab].running;
  }

  get stopping(): boolean {
    return this.#stopRequested || this.options.stopping();
  }

  /** Start a run with *request*, unless one cannot start; a refusal is reported as *failure*. */
  async start(request: () => Promise<void>, failure: string) {
    if (this.blocked || this.starting) return;
    this.starting = true;
    this.feedback.clear();
    try {
      await request();
    } catch (error) {
      this.feedback.error(errorMessage(error, failure));
    } finally {
      this.starting = false;
    }
  }

  /** Ask the run to stop with *request*; a refusal is reported as *failure*. */
  async stop(request: () => Promise<void>, failure: string) {
    if (this.#stopRequested) return;
    this.#stopRequested = true;
    this.feedback.clear();
    try {
      await request();
    } catch (error) {
      this.feedback.error(errorMessage(error, failure));
    } finally {
      this.#stopRequested = false;
    }
  }
}
