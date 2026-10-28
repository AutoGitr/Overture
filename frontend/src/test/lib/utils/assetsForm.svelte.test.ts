import { beforeEach, describe, expect, it } from "vitest";
import type { LibrarySectionRead } from "../../../generated/rest/types.gen";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import { AssetsForm } from "../../../lib/utils/assetsForm.svelte";
import { bulkAssetsSchedule } from "../../helpers/fixtures";

const movies: LibrarySectionRead[] = [{ id: "1", title: "Movies", count: 10 }];
const shows: LibrarySectionRead[] = [{ id: "2", title: "Shows", count: 4 }];

function form({ dataset = true, loaded = true } = {}) {
  return new AssetsForm({
    movieLibraries: () => movies,
    showLibraries: () => shows,
    librariesLoaded: () => loaded,
    publicDatasetEnabled: () => dataset,
    collectionGroups: () => ["Sagas", "Studios"],
  });
}

describe("AssetsForm", () => {
  beforeEach(() => {
    localStorage.clear();
    sidebarState.current = null;
  });

  it("can run only once libraries, art types and sources are chosen", () => {
    const assets = form();
    assets.config.enableThemes = false;
    expect(assets.canRun).toBe(false);

    assets.toggleLibrary("1");
    expect(assets.canRun).toBe(false);

    assets.toggleArtType("poster");
    expect(assets.canRun).toBe(true);
    expect(assets.request()).toMatchObject({
      library_ids: ["1"],
      art: { art_types: ["poster"] },
      themes: null,
    });
  });

  it("drops season posters while no show library is selected", () => {
    const assets = form();
    assets.toggleLibrary("1");
    assets.toggleArtType("season_poster");
    expect(assets.artTypesToRun).toEqual([]);

    assets.toggleLibrary("2");
    expect(assets.hasShowLibraries).toBe(true);
    expect(assets.artTypesToRun).toEqual(["season_poster"]);
  });

  it("leaves OvertureDB sources out while the catalog is off, without unselecting them", () => {
    const assets = form({ dataset: false });

    assets.toggleArtSource("overturedb");

    expect(assets.config.selectedArtSources).toContain("overturedb");
    expect(assets.activeArtSources).not.toContain("overturedb");
    expect(assets.disabledSources).toContain("overturedb");
  });

  it("selects every library, or the sidebar's items instead", () => {
    const assets = form();
    assets.toggleAll(true);
    expect(assets.selectedLibraries).toEqual(["1", "2"]);

    assets.config.useSidebarItems = true;
    sidebarState.current = { type: "show", itemIds: [5, 6] };
    expect(assets.hasSelectedLibraries).toBe(true);
    expect(assets.hasShowLibraries).toBe(true);
    expect(assets.request()).toMatchObject({ library_ids: [], item_ids: [5, 6] });

    assets.toggleLibrary("1");
    expect(assets.config.useSidebarItems).toBe(false);
    expect(assets.selectedLibraries).toEqual(["1"]);
  });

  it("loads a saved schedule's options for editing", () => {
    const assets = form();
    const schedule = bulkAssetsSchedule({
      config: {
        library_ids: ["2", "gone"],
        item_ids: null,
        collection_ids: null,
        collection_groups: null,
        all_collections: false,
        include_unmonitored: true,
        overwrite_existing: true,
        skip_recent_val: 3,
        skip_recent_unit: "days",
        art: { art_types: ["background"], source_order: ["local_art_matching"], threshold: 4 },
        themes: null,
      },
    });

    assets.applySchedule(schedule);

    expect(assets.config).toMatchObject({
      selectedLibraries: ["2"],
      includeUnmonitored: true,
      overwriteExisting: true,
      skipRecentVal: 3,
      skipRecentUnit: "days",
      enableArt: true,
      enableThemes: false,
      artTypes: ["background"],
      selectedArtSources: ["local_art_matching"],
      threshold: 4,
      scheduleCronExpression: "0 4 * * *",
    });
  });
});

describe("collection theme scope", () => {
  beforeEach(() => {
    localStorage.clear();
    sidebarState.current = null;
    sidebarState.collections = null;
  });

  it("runs art and themes over the sidebar's collection rows", () => {
    sidebarState.collections = { type: "movie", collectionIds: [12, 34] };
    const assets = form();
    assets.config.useSidebarItems = true;
    assets.config.artTypes = ["poster"];
    expect(assets.canRun).toBe(true);
    expect(assets.request()).toMatchObject({
      library_ids: [],
      collection_ids: [12, 34],
      art: { art_types: ["poster"] },
    });
    expect(assets.request().item_ids).toBeUndefined();
    assets.config.enableThemes = false;
    expect(assets.canRun).toBe(true);
    sidebarState.collections = null;
  });

  it("persists the opt-in collection setting with a library theme run", () => {
    const assets = form();
    assets.toggleLibrary("1");
    assets.config.enableArt = false;
    assets.config.includeCollections = true;
    expect(assets.request().themes?.include_collections).toBe(true);
    expect(assets.request().collection_ids).toBeUndefined();
  });

  it("runs over every collection, or the chosen groups, with collection art", () => {
    const assets = form();
    assets.config.scope = "collections";
    assets.config.artTypes = ["poster", "season_poster"];

    expect(assets.canRun).toBe(true);
    expect(assets.request()).toMatchObject({
      library_ids: [],
      all_collections: true,
      art: { art_types: ["poster"] },
    });

    assets.toggleCollectionGroup("Sagas");
    expect(assets.request()).toMatchObject({ collection_groups: ["Sagas"] });
    expect(assets.request()).not.toHaveProperty("all_collections");
  });

  it("loads a saved collection-group schedule into the Collections scope", () => {
    const assets = form();
    assets.applySchedule(
      bulkAssetsSchedule({
        config: {
          ...bulkAssetsSchedule().config,
          library_ids: [],
          collection_groups: ["Studios", "gone"],
        },
      }),
    );

    expect(assets.config.scope).toBe("collections");
    expect(assets.selectedCollectionGroups).toEqual(["Studios"]);
  });
});
