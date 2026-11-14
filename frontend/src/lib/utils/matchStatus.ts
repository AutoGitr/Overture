import { countOf } from "./plural";
import type { ArtMatchResponse } from "../../generated/rest/types.gen";
import { MATCH_THRESHOLD_DEFAULT, MATCH_THRESHOLD_MAX } from "../../generated/settings";

/**
 * The words a match outcome is reported in.
 *
 * A bulk run writes these reasons into its job log from
 * `src/overture/services/art/bulk.py`; a single-slot match builds its own line from
 * the REST response. Both read "<Outcome> - <reason>", so the same situation
 * is described the same way wherever the user meets it.
 */
export const REJECTED_CANDIDATES = "rejected on size or aspect ratio";

/** What the candidates were compared against, as said in a status line. */
const REFERENCE_LABELS: Record<NonNullable<ArtMatchResponse["reference"]>, string> = {
  local_file: "the local file",
  media_server: "the media server's image",
  saved_url: "the saved URL's image",
};

/** A stored threshold as a whole pHash distance from 0 to the backend's maximum. */
export function clampMatchThreshold(value: unknown): number {
  if (value === null || value === undefined || value === "") return MATCH_THRESHOLD_DEFAULT;
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return MATCH_THRESHOLD_DEFAULT;
  return Math.max(0, Math.min(MATCH_THRESHOLD_MAX, Math.round(parsed)));
}

export interface MatchStatus {
  /** The line to show. */
  text: string;
  /** Whether the slot needs nothing further: at least one candidate matched. */
  settled: boolean;
}

/** Describe what a single-slot match found, and why. */
export function matchStatusLine(result: ArtMatchResponse, threshold: number): MatchStatus {
  const rejected = result.prefiltered || 0;
  const rejectedNote = rejected > 0 ? `, ${rejected} ${REJECTED_CANDIDATES}` : "";
  const errors = [...(result.errors || [])];
  if (result.failed) errors.push(`could not compare ${result.failed} artwork candidates`);
  const errorNote = errors.length ? `; incomplete comparison: ${errors.join("; ")}` : "";
  const against = result.reference ? ` against ${REFERENCE_LABELS[result.reference]}` : "";

  const matches = result.matches?.length || 0;
  if (matches > 0) {
    const perfect = result.matches?.filter((match) => match.perfect_match).length || 0;
    const perfectNote = perfect ? `, ${perfect} identical to the local file` : "";
    return {
      text: `Matched ${matches} of ${result.total_compared || 0} compared${against}${perfectNote}${rejectedNote}${errorNote}`,
      settled: true,
    };
  }

  if (errors.length) return { text: `Error - ${errors.join("; ")}`, settled: false };
  if (result.reason) return { text: `No match - ${result.reason}`, settled: false };
  if (!result.total_compared) {
    const reason = rejected
      ? `${countOf(rejected, "candidate")} ${REJECTED_CANDIDATES}`
      : "no candidates returned by enabled artwork providers";
    return { text: `No match - ${reason}`, settled: false };
  }

  return {
    text: `No match - nothing within distance ${threshold}${against}${rejectedNote}`,
    settled: false,
  };
}
