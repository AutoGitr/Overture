import { describe, expect, it } from "vitest";
import { logEntryTime } from "../../../lib/utils/jobLog";
import { logEntry } from "../../helpers/fixtures";

describe("logEntryTime", () => {
  it("shows the time of day the entry was written, to the second", () => {
    const at = new Date(2026, 0, 2, 7, 5, 9).toISOString();

    expect(logEntryTime(logEntry("Added", "Alien", "new library item", at))).toMatch(/^0?7.05.09$/);
  });
});
