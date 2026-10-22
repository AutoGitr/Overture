import { describe, expect, it } from "vitest";
import type { JobOutcome } from "../../../generated/ws";
import { OUTCOME_TONES, logEntryTime } from "../../../lib/utils/jobLog";
import { logEntry } from "../../helpers/fixtures";

describe("OUTCOME_TONES", () => {
  it.each<[JobOutcome, string]>([
    ["Added", "success"],
    ["Downloaded", "success"],
    ["Unchanged", "muted"],
    ["Skipped", "muted"],
    ["Queued", "info"],
    ["Mismatch", "warning"],
    ["No match", "warning"],
    ["Error", "danger"],
  ])("colours %s as %s", (outcome, tone) => {
    expect(OUTCOME_TONES[outcome]).toBe(tone);
  });
});

describe("logEntryTime", () => {
  it("shows the time of day the entry was written, to the second", () => {
    const at = new Date(2026, 0, 2, 7, 5, 9).toISOString();

    expect(logEntryTime(logEntry("Added", "Alien", "new library item", at))).toMatch(/^0?7.05.09$/);
  });
});
