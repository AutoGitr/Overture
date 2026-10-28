import { describe, expect, it, vi } from "vitest";
import { hasVisibleActiveFilters } from "../../../lib/utils/sidebarDomain";

describe("uiState popups", () => {
  it("never reflects the open popup in the URL (path, hash, or search params)", async () => {
    vi.resetModules();

    const { uiState } = await import("../../../lib/stores/uiState.svelte");
    // Importing uiState pulls in the router, which normalizes the URL once
    // on load (e.g. to a default route) - capture the baseline *after*
    // that settles, so we're only asserting popups themselves never touch it.
    const originalHref = window.location.href;

    uiState.openPopupByName("settings");
    expect(uiState.openPopup).toBe("settings");
    // Opening/closing a popup is pure in-memory UI state - it must never be
    // written to the address bar, so it can't be linked, bookmarked, or
    // recreated by browser back/forward navigation.
    expect(window.location.href).toBe(originalHref);

    uiState.openPopupByName("operations");
    expect(uiState.openPopup).toBe("operations");
    expect(window.location.href).toBe(originalHref);

    uiState.closePopup();
    expect(uiState.openPopup).toBeNull();
    expect(window.location.href).toBe(originalHref);
  });
});

describe("uiState persisted filters", () => {
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
        themeSources: ["download", "youtube", 3],
        artSource: { sources: ["tpdb", "imgur", 1], artType: "season_poster" },
        metadataIssues: { flags: ["no_tmdb_id", "no_poster", 7, null], mode: "invalid" },
        resolution: { artType: "icon", min: -20, max: "2000" },
        themeLength: { min: 30, max: Number.POSITIVE_INFINITY },
        // Keys a removed filter left behind drop out.
        collectionCard: "smart",
        tmdbCollectionSearch: "8091",
      }),
    );

    const { uiState } = await import("../../../lib/stores/uiState.svelte");

    expect(uiState.movieFilters).toEqual({
      monitored: "monitored",
      collectionSize: "all",
      collectionKind: "all",
      collectionMembers: "all",
      collectionSync: "all",
      art: "complete",
      theme: "all",
      overtureDb: "complete",
      themerrDb: "all",
      aspectRatio: "all",
      mediaServer: "all",
      libraryIds: [],
      themeSources: ["download"],
      artSource: { sources: ["tpdb"], artType: "any" },
      metadataIssues: { flags: ["no_tmdb_id"], mode: "all" },
      resolution: { artType: "poster", min: null, max: null },
      themeLength: { min: 30, max: null },
    });
    expect(hasVisibleActiveFilters(uiState.currentFilters, true, "items")).toBe(true);
  });

  it("persists filters for the next session", async () => {
    vi.resetModules();
    const { uiState } = await import("../../../lib/stores/uiState.svelte");

    uiState.movieFilters.art = "incomplete";
    uiState.movieFilters.mediaServer = "missing";
    uiState.movieFilters.collectionSize = "empty";
    uiState.saveFilters();

    expect(JSON.parse(localStorage.getItem("movieFilters")!)).toMatchObject({
      art: "incomplete",
      mediaServer: "missing",
      collectionSize: "empty",
    });
  });

  it("stores cleared and non-positive range bounds as open", async () => {
    vi.resetModules();
    const { defaultFilters, uiState } = await import("../../../lib/stores/uiState.svelte");

    uiState.setFilters({
      ...defaultFilters(),
      resolution: { artType: "background", min: 0, max: 4000 },
      themeLength: { min: -5, max: null },
    });

    expect(uiState.movieFilters.resolution).toEqual({
      artType: "background",
      min: null,
      max: 4000,
    });
    expect(uiState.movieFilters.themeLength).toEqual({ min: null, max: null });
  });
});
