import { describe, expect, it } from "vitest";
import { formatDateInTimezone, formatDuration } from "../../../lib/utils/popupFormat";

describe("formatDateInTimezone", () => {
  const iso = "2026-06-02T22:30:00Z";

  it("formats in the given timezone", () => {
    expect(formatDateInTimezone(iso, "Asia/Tokyo")).not.toBe(formatDateInTimezone(iso, "UTC"));
  });

  it("uses the browser's timezone when the server sends none", () => {
    const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(formatDateInTimezone(iso, null)).toBe(formatDateInTimezone(iso, browserZone));
  });
});

describe("formatDuration", () => {
  it("scales the unit to the length", () => {
    expect(formatDuration(0.25)).toBe("250ms");
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(4.53)).toBe("4.5s");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(123.9)).toBe("2m 3s");
    expect(formatDuration(3723)).toBe("1h 2m 3s");
  });

  it("leaves unknown and invalid lengths blank", () => {
    expect(formatDuration(null)).toBe("");
    expect(formatDuration(undefined)).toBe("");
    expect(formatDuration(Number.NaN)).toBe("");
    expect(formatDuration(-1)).toBe("");
  });
});
