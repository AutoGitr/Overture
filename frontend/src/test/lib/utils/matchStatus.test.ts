import { describe, expect, it } from "vitest";
import type { ArtMatchResponse } from "../../../generated/rest/types.gen";
import {
  DEFAULT_MATCH_THRESHOLD,
  MAX_MATCH_THRESHOLD,
  MIN_MATCH_THRESHOLD,
  clampMatchThreshold,
  matchStatusLine,
} from "../../../lib/utils/matchStatus";

function response(overrides: Partial<ArtMatchResponse> = {}): ArtMatchResponse {
  return {
    matches: [],
    prefiltered: 0,
    skipped: false,
    total_compared: 0,
    ...overrides,
  } as ArtMatchResponse;
}

const candidate = { url: "https://images.test/poster.jpg" } as ArtMatchResponse["matches"][0];

describe("matchStatusLine", () => {
  it.each([
    [{}, "No match - no candidates returned by enabled artwork providers"],
    [{ reason: "no usable reference image" }, "No match - no usable reference image"],
    [{ prefiltered: 2 }, "No match - 2 candidates rejected on size or aspect ratio"],
    [{ failed: 2 }, "Error - could not compare 2 artwork candidates"],
    [{ errors: ["server unavailable"] }, "Error - server unavailable"],
  ] satisfies [Partial<ArtMatchResponse>, string][])(
    "explains incomplete and empty comparisons",
    (result, text) => {
      expect(matchStatusLine(response(result), 5)).toEqual({ text, settled: false });
    },
  );

  it("reports partial failures alongside successful matches", () => {
    expect(
      matchStatusLine(response({ matches: [candidate], total_compared: 1, failed: 1 }), 5).text,
    ).toBe(
      "Matched 1 of 1 compared; incomplete comparison: could not compare 1 artwork candidates",
    );
  });
  it("names the reference and how many candidates are identical to the local file", () => {
    const status = matchStatusLine(
      response({
        matches: [{ ...candidate, perfect_match: true }],
        total_compared: 3,
        reference: "local_file",
      }),
      5,
    );

    expect(status).toEqual({
      text: "Matched 1 of 3 compared against the local file, 1 identical to the local file",
      settled: true,
    });
  });

  it("reports how many candidates matched out of those compared", () => {
    const status = matchStatusLine(response({ matches: [candidate], total_compared: 4 }), 5);

    expect(status).toEqual({ text: "Matched 1 of 4 compared", settled: true });
  });

  it("names the distance that nothing came within", () => {
    expect(matchStatusLine(response({ total_compared: 3 }), 5).text).toBe(
      "No match - nothing within distance 5",
    );
  });

  it("counts candidates that never reached the comparison", () => {
    expect(matchStatusLine(response({ total_compared: 1, prefiltered: 7 }), 5).text).toBe(
      "No match - nothing within distance 5, 7 rejected on size or aspect ratio",
    );
  });

  it("exports the default threshold of 3 and valid bounds", () => {
    expect(DEFAULT_MATCH_THRESHOLD).toBe(3);
    expect(MIN_MATCH_THRESHOLD).toBe(0);
    expect(MAX_MATCH_THRESHOLD).toBe(10);
  });

  it("clamps and sanitizes match thresholds into bounds", () => {
    expect(clampMatchThreshold(undefined)).toBe(3);
    expect(clampMatchThreshold(null)).toBe(3);
    expect(clampMatchThreshold("invalid")).toBe(3);
    expect(clampMatchThreshold(3)).toBe(3);
    expect(clampMatchThreshold(-2)).toBe(0);
    expect(clampMatchThreshold(15)).toBe(10);
    expect(clampMatchThreshold(2.7)).toBe(3);
  });
});
