import type { JobLogEntry, JobOutcome } from "../../generated/ws";
import { keysOf } from "./records";

export type LogTone = "info" | "success" | "warning" | "danger" | "muted";

/**
 * How each job outcome is coloured.
 *
 * Entries carry their outcome as a field (see `src/overture/jobs/progress_log.py`),
 * so the same outcome looks the same in every job's log, and a new outcome
 * fails the type check until it has a tone here.
 */
export const OUTCOME_TONES: Record<JobOutcome, LogTone> = {
  Started: "info",
  Added: "success",
  Updated: "success",
  Unchanged: "muted",
  Removed: "warning",
  Queued: "info",
  Downloaded: "success",
  Adopted: "success",
  Matched: "success",
  Mismatch: "warning",
  Checked: "info",
  "No match": "warning",
  Skipped: "muted",
  Error: "danger",
};

/** Every outcome, in the order its filter is offered. */
export const OUTCOMES = keysOf(OUTCOME_TONES);

const TIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/** Return when the job wrote the entry, as the reader's local time of day. */
export function logEntryTime(entry: JobLogEntry): string {
  return TIME_FORMAT.format(new Date(entry.at));
}
