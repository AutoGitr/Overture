import { describe, expect, it } from "vitest";
import { assetsInScope } from "../../../lib/utils/artTypes";

describe("assetsInScope", () => {
  it("keeps nothing when the scope selects nothing", () => {
    expect(
      assetsInScope(["poster", "season_poster"], { hasSelection: false, hasShows: true }),
    ).toEqual([]);
  });

  it("keeps every chosen asset when the scope reaches shows", () => {
    expect(
      assetsInScope(["poster", "season_poster", "theme"], { hasSelection: true, hasShows: true }),
    ).toEqual(["poster", "season_poster", "theme"]);
  });

  it("drops season artwork when the scope reaches no shows", () => {
    expect(
      assetsInScope(["poster", "season_poster", "theme"], { hasSelection: true, hasShows: false }),
    ).toEqual(["poster", "theme"]);
  });
});
