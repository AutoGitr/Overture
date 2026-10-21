import { describe, expect, it } from "vitest";
import { formatElapsedTime } from "../../../lib/utils/jobTime";

describe("formatElapsedTime", () => {
  it("formats running and completed durations from stable timestamps", () => {
    expect(formatElapsedTime("2026-06-02T10:00:00Z", Date.parse("2026-06-02T10:02:03Z"))).toBe(
      "2m 3s",
    );
    expect(formatElapsedTime("2026-06-02T10:00:00Z", "2026-06-02T11:02:03Z")).toBe("1h 2m 3s");
    expect(formatElapsedTime("2026-06-02T10:00:00Z", "2026-06-02T10:00:42Z")).toBe("42s");
  });

  it("handles invalid and out-of-order timestamps", () => {
    expect(formatElapsedTime("invalid", Date.parse("2026-06-02T10:00:00Z"))).toBe("");
    expect(formatElapsedTime("2026-06-02T10:00:00Z", "invalid")).toBe("");
    expect(formatElapsedTime("2026-06-02T10:00:01Z", "2026-06-02T10:00:00Z")).toBe("0s");
  });
});
