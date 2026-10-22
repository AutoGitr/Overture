import { afterEach, describe, expect, it, vi } from "vitest";
import { serverClock } from "../../../lib/realtime/serverClock";

describe("serverClock", () => {
  afterEach(() => {
    serverClock.sync(new Date().toISOString());
  });

  it("reports the server's time when the browser clock is ahead", () => {
    vi.useFakeTimers({ now: Date.parse("2026-06-02T10:00:04Z"), toFake: ["Date", "performance"] });

    serverClock.sync("2026-06-02T10:00:00Z");
    vi.advanceTimersByTime(2000);

    expect(serverClock.isoNow()).toBe("2026-06-02T10:00:02.000Z");
  });

  it("ignores an unreadable server time", () => {
    vi.useFakeTimers({ now: Date.parse("2026-06-02T10:00:00Z"), toFake: ["Date", "performance"] });

    serverClock.sync("2026-06-02T09:00:00Z");
    serverClock.sync("invalid");

    expect(serverClock.now).toBe(Date.parse("2026-06-02T09:00:00Z"));
  });

  it("keeps elapsed time steady when the browser wall clock changes", () => {
    vi.useFakeTimers({ now: Date.parse("2026-06-02T10:00:00Z"), toFake: ["Date", "performance"] });
    serverClock.sync("2026-06-02T10:00:00Z");
    vi.advanceTimersByTime(2000);
    vi.setSystemTime("2026-06-02T10:05:00Z");
    expect(serverClock.isoNow()).toBe("2026-06-02T10:00:02.000Z");
    vi.advanceTimersByTime(1000);
    expect(serverClock.isoNow()).toBe("2026-06-02T10:00:03.000Z");
  });
});
