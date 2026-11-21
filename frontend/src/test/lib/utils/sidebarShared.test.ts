import { describe, expect, it } from "vitest";
import {
  catalogStatus,
  inCollectionGroup,
  preloadRowIndexes,
  statusTone,
} from "../../../lib/utils/sidebarShared";
import { catalogRow } from "../../helpers/fixtures";

describe("catalog badge status", () => {
  it("uses the same selections for detail and sidebar tones", () => {
    const entry = catalogRow({
      media_type: "show",
      poster_url: "https://images.test/poster.jpg",
      background_url: "https://images.test/background.jpg",
    });
    expect(catalogStatus(entry).art).toBe("warning");
    expect(catalogStatus({ ...entry, season_posters: 1 })).toEqual(
      catalogStatus({
        ...entry,
        seasons: [{ season_num: 1, poster_url: "https://images.test/season.jpg" }],
      }),
    );
    expect(catalogStatus({ ...entry, season_posters: 1 }).art).toBe("success");
  });
});

describe("status tones", () => {
  it("shows the backend's asset status as a tone, or downloading while a job runs", () => {
    expect(statusTone("complete", false)).toBe("success");
    expect(statusTone("partial", false)).toBe("warning");
    expect(statusTone("missing", false)).toBe("danger");
    expect(statusTone("complete", true)).toBe("downloading");
  });
});

describe("sidebar thumbnail preloading", () => {
  it("covers two screens past the mounted rows, below first, nearest first", () => {
    // Rows 100-104 on screen, so rows 80-124 are mounted (20 overscan each way).
    expect(preloadRowIndexes(100, 105, 1000)).toEqual([
      125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 79, 78, 77, 76, 75, 74, 73, 72, 71, 70,
    ]);
  });

  it("stays inside the list", () => {
    expect(preloadRowIndexes(0, 10, 35)).toEqual([30, 31, 32, 33, 34]);
    expect(preloadRowIndexes(0, 0, 0)).toEqual([]);
  });
});

describe("inCollectionGroup", () => {
  it("puts collections without rules in the virtual Unmanaged group", () => {
    const imported = { collection_group: "Weekend", managed: false };
    const managed = { collection_group: "Weekend", managed: true };
    expect(inCollectionGroup(imported, "Unmanaged")).toBe(true);
    expect(inCollectionGroup(managed, "Unmanaged")).toBe(false);
    expect(inCollectionGroup(imported, "Weekend")).toBe(false);
    expect(inCollectionGroup(managed, "Weekend")).toBe(true);
  });

  it("lists only managed collections without a group at the top level", () => {
    expect(inCollectionGroup({ collection_group: null, managed: true }, null)).toBe(true);
    expect(inCollectionGroup({ collection_group: null, managed: false }, null)).toBe(false);
    expect(inCollectionGroup({ collection_group: "Weekend", managed: true }, null)).toBe(false);
  });
});
