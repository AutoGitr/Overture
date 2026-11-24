import { describe, expect, it, vi } from "vitest";
import { activeFilterCount } from "../../../lib/utils/sidebarFilters";

describe("persisted filters", () => {
  it("normalizes malformed stored filters before exposing them to the UI", async () => {
    vi.resetModules();
    localStorage.setItem(
      "movieFilters",
      JSON.stringify({
        monitored: "monitored",
        art: "complete",
        theme: "unknown",
        overtureDb: "complete",
        themerrDb: "invalid",
        aspectRatio: "sideways",
        mediaServer: "invalid",
        libraryIds: "not-an-array",
        collectionId: "12",
        themeSources: ["download", "youtube", 3],
        artSource: { sources: ["tpdb", "imgur", 1], artType: "season_poster" },
        metadataIssues: { flags: ["no_tmdb_id", "no_poster", 7, null], mode: "invalid" },
        resolution: { artType: "icon", min: -20, max: "2000" },
        themeLength: { min: 30, max: Number.POSITIVE_INFINITY },
      }),
    );

    const { filterState } = await import("../../../lib/stores/filterState.svelte");

    expect(filterState.movie).toEqual({
      monitored: "monitored",
      collectionSize: "all",
      collectionKind: "all",
      collectionHolds: "all",
      collectionOrigin: "all",
      collectionMembers: "all",
      collectionSync: "all",
      art: "complete",
      theme: "all",
      seasonPosters: "all",
      overtureDb: "complete",
      themerrDb: "all",
      catalogPoster: "all",
      catalogBackground: "all",
      catalogSeasonPosters: "all",
      catalogTheme: "all",
      aspectRatio: "all",
      mediaServer: "all",
      libraryIds: [],
      collectionId: null,
      customFilter: null,
      themeSources: ["download"],
      artSource: { sources: ["tpdb"], artType: "any" },
      metadataIssues: { flags: ["no_tmdb_id"], mode: "all" },
      resolution: { artType: "any", min: null, max: null },
      themeLength: { min: 30, max: null },
    });
    expect(activeFilterCount(filterState.current, true, "items")).toBeGreaterThan(0);
  });

  it("persists filters for the next session", async () => {
    vi.resetModules();
    const { filterState } = await import("../../../lib/stores/filterState.svelte");

    filterState.movie.art = "incomplete";
    filterState.movie.mediaServer = "missing";
    filterState.movie.collectionSize = "empty";
    filterState.save();

    expect(JSON.parse(localStorage.getItem("movieFilters")!)).toMatchObject({
      art: "incomplete",
      mediaServer: "missing",
      collectionSize: "empty",
    });
  });

  it("stores cleared and non-positive range bounds as open", async () => {
    vi.resetModules();
    const { defaultFilters, filterState } = await import("../../../lib/stores/filterState.svelte");

    filterState.set({
      ...defaultFilters(),
      resolution: { artType: "background", min: 0, max: 4000 },
      themeLength: { min: -5, max: null },
    });

    expect(filterState.movie.resolution).toEqual({
      artType: "background",
      min: null,
      max: 4000,
    });
    expect(filterState.movie.themeLength).toEqual({ min: null, max: null });
  });
});
