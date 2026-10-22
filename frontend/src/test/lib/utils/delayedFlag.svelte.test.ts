import { flushSync } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SETTLE_DELAY_MS, delayedFlag } from "../../../lib/utils/delayedFlag.svelte";

describe("delayedFlag", () => {
  beforeEach(() => vi.useFakeTimers());

  it("keeps its delay running while the source hands over between states", () => {
    let pending = $state(false);
    let running = $state(false);
    let flag: { current: boolean } | undefined;
    const cleanup = $effect.root(() => {
      flag = delayedFlag(() => pending || running);
    });

    pending = true;
    flushSync();
    vi.advanceTimersByTime(SETTLE_DELAY_MS - 100);
    pending = false;
    running = true;
    flushSync();
    vi.advanceTimersByTime(100);
    expect(flag?.current).toBe(true);

    running = false;
    flushSync();
    expect(flag?.current).toBe(false);
    cleanup();
  });
});
