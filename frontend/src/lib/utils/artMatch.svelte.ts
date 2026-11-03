import type { ArtCandidate, ArtMatchResponse, ArtType } from "../../generated/rest/types.gen";
import { errorMessage } from "./errors";
import { DEFAULT_MATCH_THRESHOLD, clampMatchThreshold, matchStatusLine } from "./matchStatus";
import { readJson, writeJson } from "./storage";

const THRESHOLD_KEY = "artPanel_threshold";

/** What matching one stored slot asks the server. */
export type ArtMatchRequest = {
  path: { item_id: number; art_type: ArtType };
  query: { season_id: number | null; threshold: number };
};

/** One slot's perceptual-hash match: its threshold, the run and what it found. */
export class ArtMatch {
  threshold = $state(clampMatchThreshold(readJson(THRESHOLD_KEY, DEFAULT_MATCH_THRESHOLD)));
  results = $state.raw<ArtCandidate[] | null>(null);
  loading = $state(false);
  ran = $state(false);
  status = $state("");
  settled = $state(false);

  constructor(private readonly request: (args: ArtMatchRequest) => Promise<ArtMatchResponse>) {}

  /** Keep the threshold within range and remember it for the next slot. */
  saveThreshold(): number {
    this.threshold = clampMatchThreshold(this.threshold);
    writeJson(THRESHOLD_KEY, this.threshold);
    return this.threshold;
  }

  async run(itemId: number, artType: ArtType, seasonId: number | null): Promise<void> {
    if (this.loading) return;
    const threshold = this.saveThreshold();
    this.loading = true;
    this.ran = true;
    this.results = null;
    this.status = "";
    this.settled = false;
    try {
      const result = await this.request({
        path: { item_id: itemId, art_type: artType },
        query: { season_id: seasonId, threshold },
      });
      this.results = result.matches || [];
      ({ text: this.status, settled: this.settled } = matchStatusLine(result, threshold));
    } catch (err) {
      this.status = `Error - ${errorMessage(err, "unknown error")}`;
    } finally {
      this.loading = false;
    }
  }
}
