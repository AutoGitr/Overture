import { describe, expect, it } from "vitest";
import {
  BUILDER_KINDS,
  emptyFilterGroup,
  emptySmartFilter,
  newBuilder,
  splitIds,
  splitList,
} from "../../../lib/utils/collectionBuilders";

describe("collectionBuilders utilities", () => {
  it("creates empty filter group and smart filter with default values", () => {
    const group = emptyFilterGroup();
    expect(group).toEqual({ mode: "all", conditions: [], groups: [] });

    const smart = emptySmartFilter();
    expect(smart).toEqual({
      filter_group: { mode: "all", conditions: [], groups: [] },
      sort_by: "release.desc",
      limit: null,
    });
  });

  it("creates new builder instances for every supported type", () => {
    expect(newBuilder("tmdb_collection")).toEqual({ type: "tmdb_collection", collection_id: 0 });
    expect(newBuilder("tmdb_item")).toEqual({ type: "tmdb_item", tmdb_ids: [] });
    expect(newBuilder("tmdb_person")).toEqual({
      type: "tmdb_person",
      person_id: 0,
      roles: ["actor"],
      use_biography: false,
    });
    expect(newBuilder("mdblist")).toEqual({ type: "mdblist", identifiers: [""] });
    expect(newBuilder("radarr_tag")).toEqual({ type: "radarr_tag", tags: [] });
    expect(newBuilder("sonarr_tag")).toEqual({ type: "sonarr_tag", tags: [] });
    expect(newBuilder("library_filter")).toEqual({
      type: "library_filter",
      filter_group: { mode: "all", conditions: [], groups: [] },
    });
  });

  it("splits text into trimmed non-empty lists by comma and newline", () => {
    expect(splitList("")).toEqual([]);
    expect(splitList("  \n  ,  \n")).toEqual([]);
    expect(splitList("alpha, beta, gamma")).toEqual(["alpha", "beta", "gamma"]);
    expect(splitList("first\nsecond, third\n\nfourth")).toEqual([
      "first",
      "second",
      "third",
      "fourth",
    ]);
  });

  it("splits text into valid positive integers", () => {
    expect(splitIds("")).toEqual([]);
    expect(splitIds("abc, def, -1, 0, 10, 20\n30, 0.5")).toEqual([10, 20, 30]);
  });

  it("exports builder kinds catalog with media constraints", () => {
    expect(BUILDER_KINDS.length).toBeGreaterThan(5);
    const tmdbColl = BUILDER_KINDS.find((k) => k.type === "tmdb_collection");
    expect(tmdbColl?.media).toBe("movie");
    const sonarr = BUILDER_KINDS.find((k) => k.type === "sonarr_tag");
    expect(sonarr?.media).toBe("show");
  });
});
