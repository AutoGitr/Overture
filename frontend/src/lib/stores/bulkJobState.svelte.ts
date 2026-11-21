import type { BulkArtJobEvent, BulkThemeJobEvent } from "../../generated/ws";
import { JobLifecycleState } from "./jobLifecycleState.svelte";

/**
 * A bulk art or theme run: what it decided for each item, and the downloads
 * it queued. `settled` counts the queued downloads that have ended.
 */
export class BulkJobState<
  T extends BulkArtJobEvent | BulkThemeJobEvent,
> extends JobLifecycleState<T> {
  settled = $state(0);

  constructor(failureMessage: string) {
    super({ failureMessage });
  }

  /** The queued downloads that are still waiting or running. */
  get unsettled(): number {
    return this.count("Queued") - this.settled;
  }

  /** Whether deciding is over and the run is waiting for its downloads to settle. */
  get downloading(): boolean {
    return this.running && this.total !== null && this.done >= this.total && this.unsettled > 0;
  }

  protected override absorb(data: T) {
    this.settled = data.settled ?? this.settled;
  }

  protected override resetLifecycle() {
    super.resetLifecycle();
    this.settled = 0;
  }
}

export const matchState = new BulkJobState<BulkArtJobEvent>("Art matching failed");
export const themeJobState = new BulkJobState<BulkThemeJobEvent>("Theme matching failed");
