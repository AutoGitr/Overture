import type { BulkArtJobEvent, BulkThemeJobEvent } from "../../generated/ws";
import { JobLifecycleState } from "./jobLifecycleState.svelte";

const BULK_COUNTERS = [
  "queued",
  "downloaded",
  "adopted",
  "skipped",
  "no_match",
  "settled",
] as const;

type BulkCounter = (typeof BULK_COUNTERS)[number];

/**
 * A bulk art or theme run: what it decided for each item, and the downloads
 * it queued. `settled` counts the queued downloads that have ended.
 */
export class BulkJobState<T extends BulkArtJobEvent | BulkThemeJobEvent> extends JobLifecycleState<
  T,
  BulkCounter
> {
  constructor(failureMessage: string) {
    super({ failureMessage, counters: BULK_COUNTERS });
  }

  /** Whether deciding is over and the run is waiting for its downloads to settle. */
  get downloading(): boolean {
    const { queued, settled } = this.counters;
    return this.running && this.total !== null && this.done >= this.total && settled < queued;
  }
}

export const themeJobState = new BulkJobState<BulkThemeJobEvent>("Theme matching failed");
