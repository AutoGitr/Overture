import { describe, expect, it } from "vitest";
import { elapsedSeconds } from "../../../lib/utils/jobTime";

describe("elapsedSeconds", () => {
  it("counts whole seconds from timestamps or epoch milliseconds", () => {
    expect(elapsedSeconds("2026-06-02T10:00:00Z", Date.parse("2026-06-02T10:02:03Z"))).toBe(123);
    expect(elapsedSeconds("2026-06-02T10:00:00Z", "2026-06-02T10:00:42.900Z")).toBe(42);
  });

  it("handles invalid and out-of-order timestamps", () => {
    expect(elapsedSeconds("invalid", Date.parse("2026-06-02T10:00:00Z"))).toBe(0);
    expect(elapsedSeconds("2026-06-02T10:00:00Z", "invalid")).toBe(0);
    expect(elapsedSeconds("2026-06-02T10:00:05Z", "2026-06-02T10:00:00Z")).toBe(0);
  });
});
