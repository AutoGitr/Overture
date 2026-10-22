import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ArtMatchResponse } from "../../../generated/rest/types.gen";
import { ArtMatch } from "../../../lib/utils/artMatch.svelte";
import { MAX_MATCH_THRESHOLD } from "../../../lib/utils/matchStatus";
import { artCandidate, artMatchResponse } from "../../helpers/fixtures";

describe("ArtMatch", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("asks for the slot with the clamped threshold, remembering it", async () => {
    const request = vi.fn(async () => artMatchResponse({ matches: [artCandidate()] }));
    const match = new ArtMatch(request);
    match.threshold = MAX_MATCH_THRESHOLD + 5;

    await match.run(7, "season_poster", 3);

    expect(request).toHaveBeenCalledWith({
      path: { item_id: 7, art_type: "season_poster" },
      query: { season_id: 3, threshold: MAX_MATCH_THRESHOLD },
    });
    expect(match.threshold).toBe(MAX_MATCH_THRESHOLD);
    expect(new ArtMatch(request).threshold).toBe(MAX_MATCH_THRESHOLD);
    expect(match.results).toHaveLength(1);
    expect(match.settled).toBe(true);
    expect(match.status).toMatch(/^Matched 1 of 1/);
    expect(match.loading).toBe(false);
  });

  it("reports a failed request in its status line", async () => {
    const match = new ArtMatch(async () => {
      throw new Error("server unavailable");
    });

    await match.run(7, "poster", null);

    expect(match.ran).toBe(true);
    expect(match.results).toBeNull();
    expect(match.status).toBe("Error - server unavailable");
    expect(match.loading).toBe(false);
  });

  it("ignores a second run while one is in flight", async () => {
    let finish!: (value: ArtMatchResponse) => void;
    const request = vi.fn(
      () =>
        new Promise<ArtMatchResponse>((resolve) => {
          finish = resolve;
        }),
    );
    const match = new ArtMatch(request);

    const first = match.run(7, "poster", null);
    await match.run(7, "poster", null);
    finish(artMatchResponse());
    await first;

    expect(request).toHaveBeenCalledOnce();
  });
});
