import type { BulkArtJobEvent, BulkArtMatchResult } from "../../generated/ws";
import { BulkJobState } from "./bulkJobState.svelte";
import { JobResultPage } from "./jobResultPage.svelte";

/** A bulk art run, with the artwork it queued or adopted. */
class MatchState extends BulkJobState<BulkArtJobEvent> {
  /** Artwork the run queued or adopted, newest last. */
  results = $state<BulkArtMatchResult[]>([]);
  readonly page = new JobResultPage<BulkArtMatchResult>((items) => {
    this.results = items;
  });

  constructor() {
    super("Art matching failed");
  }

  override get hasRun(): boolean {
    return super.hasRun || this.results.length > 0;
  }

  override handleStarted(data: BulkArtJobEvent) {
    super.handleStarted(data);
    this.results = [];
    this.page.reset();
    this.page.update(data);
  }

  override handleProgress(data: BulkArtJobEvent) {
    super.handleProgress(data);
    if (data.result) this.results = [...this.results, data.result].slice(-this.page.size);
    this.page.update(data);
  }

  override handleCompleted(data: BulkArtJobEvent) {
    super.handleCompleted(data);
    this.replaceFinalResults(data);
  }

  override handleStopped(data: BulkArtJobEvent) {
    super.handleStopped(data);
    this.replaceFinalResults(data);
  }

  override handleFailed(data: BulkArtJobEvent) {
    super.handleFailed(data);
    this.replaceFinalResults(data);
  }

  override reset() {
    super.reset();
    this.results = [];
    this.page.reset();
  }

  private replaceFinalResults(data: BulkArtJobEvent) {
    if (data.results) this.results = data.results.slice(0, this.page.size);
    this.page.update(data, true);
  }
}

export const matchState = new MatchState();
