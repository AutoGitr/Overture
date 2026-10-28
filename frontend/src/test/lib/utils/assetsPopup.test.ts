import { describe, expect, it } from "vitest";
import type { LibrarySectionRead } from "../../../generated/rest/types.gen";
import { buildScheduleWrite, formatScheduleDate } from "../../../lib/utils/schedules.svelte";
import {
  artTypeSummary,
  buildBulkAssetsRequest,
  buildBulkAssetsStopRequest,
  disabledSources,
  enabledSources,
  libraryIds,
  librarySummary,
  moveOrderedSource,
  normaliseSelectedSources,
  normaliseSourceOrder,
  restoreLibrarySelection,
  selectAllLibraries,
  selectedIncludesShowLibrary,
  sourceDisabled,
  sourceSummary,
  workflowStatusLabel,
  workflowSummary,
} from "../../../lib/utils/assetsPopup";

function library(id: string, title: string): LibrarySectionRead {
  return { id, title, count: 0 };
}

const movieLibraries = [library("m1", "Movies")];
const showLibraries = [library("s1", "Shows")];

describe("assetsPopup library helpers", () => {
  it("combines movie and show library ids", () => {
    expect(libraryIds(movieLibraries, showLibraries)).toEqual(["m1", "s1"]);
  });

  it("restores only libraries that still exist", () => {
    expect(restoreLibrarySelection(movieLibraries, showLibraries, ["m1", "removed"])).toEqual([
      "m1",
    ]);
  });

  it("selects and clears every library", () => {
    expect(selectAllLibraries(true, movieLibraries, showLibraries)).toEqual(["m1", "s1"]);
    expect(selectAllLibraries(false, movieLibraries, showLibraries)).toEqual([]);
  });

  it("detects a show library in the current selection", () => {
    expect(selectedIncludesShowLibrary(["s1"], showLibraries)).toBe(true);
    expect(selectedIncludesShowLibrary(["m1"], showLibraries)).toBe(false);
  });
});

describe("source order helpers", () => {
  const defaults = ["local_art_matching", "overturedb"] as const;

  it("normalises a stored order, dropping unknowns and appending missing defaults", () => {
    expect(normaliseSourceOrder(["overturedb", "bogus"], defaults)).toEqual([
      "overturedb",
      "local_art_matching",
    ]);
  });

  it("normalises a stored selection down to known sources", () => {
    expect(normaliseSelectedSources(["overturedb", "bogus"], defaults)).toEqual(["overturedb"]);
  });

  it("filters enabled sources by selection and dataset availability", () => {
    expect(enabledSources(["local_art_matching", "overturedb"], ["overturedb"], false)).toEqual([]);
    expect(enabledSources(["local_art_matching", "overturedb"], ["overturedb"], true)).toEqual([
      "overturedb",
    ]);
    expect(enabledSources(["youtube_search", "themerrdb"], ["themerrdb"], false)).toEqual([]);
    expect(enabledSources(["youtube_search", "themerrdb"], ["themerrdb"], true)).toEqual([
      "themerrdb",
    ]);
    expect(
      enabledSources(
        ["local_art_matching", "overturedb"],
        ["local_art_matching", "overturedb"],
        true,
      ),
    ).toEqual(["local_art_matching", "overturedb"]);
  });

  it("moves a source next to a target without mutating the input", () => {
    const order = ["local_art_matching", "overturedb"];
    expect(moveOrderedSource(order, "overturedb", "local_art_matching")).toEqual([
      "overturedb",
      "local_art_matching",
    ]);
    expect(order).toEqual(["local_art_matching", "overturedb"]);
    expect(moveOrderedSource(order, "overturedb", "overturedb")).toBe(order);
  });

  it("reports dataset sources as disabled only when the dataset is off", () => {
    expect(sourceDisabled("overturedb", false)).toBe(true);
    expect(sourceDisabled("overturedb", true)).toBe(false);
    expect(sourceDisabled("themerrdb", false)).toBe(true);
    expect(sourceDisabled("themerrdb", true)).toBe(false);
    expect(sourceDisabled("local_art_matching", false)).toBe(false);
    expect(disabledSources(false)).toEqual(["overturedb", "themerrdb"]);
    expect(disabledSources(true)).toEqual([]);
  });
});

describe("buildBulkAssetsRequest", () => {
  it("omits art and themes when their workflow is disabled", () => {
    const request = buildBulkAssetsRequest({
      selectedLibraries: ["m1"],
      includeUnmonitored: false,
      overwriteExisting: false,
      skipRecentVal: 0,
      skipRecentUnit: "hours",
      enableArt: false,
      artTypes: ["poster"],
      activeArtSources: ["local_art_matching"],
      threshold: 3,
      enableThemes: false,
      activeThemeSources: ["youtube_search"],
    });
    expect(request.art).toBeNull();
    expect(request.themes).toBeNull();
    expect(request.library_ids).toEqual(["m1"]);
    expect(request.include_unmonitored).toBe(false);
    expect(request.overwrite_existing).toBe(false);
  });

  it("includes art and themes configuration when enabled", () => {
    const request = buildBulkAssetsRequest({
      selectedLibraries: ["m1"],
      includeUnmonitored: true,
      overwriteExisting: true,
      skipRecentVal: 12,
      skipRecentUnit: "hours",
      enableArt: true,
      artTypes: ["poster"],
      activeArtSources: ["local_art_matching"],
      threshold: 3,
      enableThemes: true,
      activeThemeSources: ["youtube_search"],
    });
    expect(request.art).toEqual({
      art_types: ["poster"],
      source_order: ["local_art_matching"],
      threshold: 3,
    });
    expect(request.themes).toEqual({
      source_order: ["youtube_search"],
      include_collections: false,
    });
    expect(request.include_unmonitored).toBe(true);
    expect(request.overwrite_existing).toBe(true);
  });
});

describe("buildBulkAssetsStopRequest", () => {
  it("mirrors which workflows are running", () => {
    expect(buildBulkAssetsStopRequest(true, false)).toEqual({ art: true, themes: false });
    expect(buildBulkAssetsStopRequest(false, false)).toEqual({ art: false, themes: false });
  });
});

describe("workflowStatusLabel", () => {
  it("prioritises downloading, running, then finished", () => {
    const job = { downloading: false, running: false, finished_at: null };
    expect(workflowStatusLabel({ ...job, downloading: true, running: true })).toBe("Downloading");
    expect(workflowStatusLabel({ ...job, status: "stopped" })).toBe("Stopped");
    expect(workflowStatusLabel({ ...job, status: "failed" })).toBe("Failed");
    expect(workflowStatusLabel({ ...job, running: true })).toBe("Running");
    expect(workflowStatusLabel({ ...job, finished_at: "2026-01-01T00:00:00Z" })).toBe("Finished");
    expect(workflowStatusLabel(job)).toBe("Results");
  });
});

describe("summary formatters", () => {
  it("summarises libraries, sources, art types, and workflows", () => {
    expect(librarySummary([], [...movieLibraries, ...showLibraries])).toBe("All libraries");
    expect(librarySummary(["m1", "missing"], [...movieLibraries, ...showLibraries])).toBe(
      "Movies, missing",
    );
    expect(sourceSummary(["overturedb"], { overturedb: "OvertureDB" })).toBe("OvertureDB");
    expect(artTypeSummary(["poster", "season_poster"])).toBe("Poster, Season Poster");
    expect(workflowSummary({ art: {}, themes: null } as never)).toBe("Art");
    expect(workflowSummary({ art: {}, themes: {} } as never)).toBe("Art + Themes");
  });

  it("formats a schedule date or falls back to a placeholder", () => {
    expect(formatScheduleDate(null, "UTC")).toBe("Not scheduled");
    expect(formatScheduleDate("2026-01-01T00:00:00Z", "UTC")).not.toBe("Not scheduled");
  });
});

describe("buildScheduleWrite", () => {
  it("trims name and cron expression", () => {
    const write = buildScheduleWrite({
      name: "  Nightly  ",
      enabled: true,
      cronExpression: " 0 3 * * * ",
      config: { library_ids: [] } as never,
    });
    expect(write.name).toBe("Nightly");
    expect(write.cron_expression).toBe("0 3 * * *");
    expect(write.enabled).toBe(true);
  });
});
