import { beforeEach, describe, expect, it } from "vitest";
import type { BulkArtMatchResult } from "../../../generated/ws";
import { matchState } from "../../../lib/stores/matchState.svelte";

function match(overrides: Partial<BulkArtMatchResult> = {}): BulkArtMatchResult {
  return {
    title: "Alien",
    art_type: "poster",
    url: "https://image.test/poster.jpg",
    source: "tmdb",
    adopted: false,
    ...overrides,
  };
}

describe("matchState", () => {
  beforeEach(() => matchState.reset());

  it("shows direct-source matches as they stream, without pHash metadata", () => {
    matchState.handleStarted({ total: 2 });
    matchState.handleProgress({ done: 1, total: 2, result: match({ source: "OvertureDB" }) });

    expect(matchState.results).toEqual([
      expect.objectContaining({ title: "Alien", source: "OvertureDB" }),
    ]);
    expect(matchState.hasRun).toBe(true);
  });

  it("clears the previous run's matches when a new one starts", () => {
    matchState.handleProgress({ done: 1, total: 1, result: match() });

    matchState.handleStarted({ total: 1 });

    expect(matchState.results).toEqual([]);
  });

  it("restores complete results from a terminal snapshot", () => {
    matchState.handleCompleted({
      done: 1,
      total: 1,
      results: [match({ hamming: 0, width: 1000, height: 1500 })],
    });

    expect(matchState.results).toEqual([
      expect.objectContaining({ title: "Alien", art_type: "poster", hamming: 0 }),
    ]);
  });

  it.each(["handleStopped", "handleFailed"] as const)(
    "keeps the terminal results of a run ended by %s",
    (handler) => {
      matchState.handleStarted({ total: 2 });

      matchState[handler]({ done: 1, total: 2, results: [match({ title: "Aliens" })] });

      expect(matchState.results.map((result) => result.title)).toEqual(["Aliens"]);
    },
  );

  it("counts a restored result as a run even before any lifecycle event", () => {
    matchState.handleCompleted({ results: [match()] });

    expect(matchState.hasRun).toBe(true);

    matchState.reset();

    expect(matchState.hasRun).toBe(false);
    expect(matchState.results).toEqual([]);
  });
});
