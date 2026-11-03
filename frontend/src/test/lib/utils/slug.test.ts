import { describe, expect, it } from "vitest";
import {
  buildIdSlug,
  parseCatalogSlug,
  parseIdFromSlug,
  parseItemSlug,
  slugify,
} from "../../../lib/utils/slug";

describe("slugify", () => {
  it.each([
    ["The Matrix", "the-matrix"],
    ["Schindler's List", "schindlers-list"],
    ["Ocean\u2019s Eleven", "oceans-eleven"],
    ["Star Wars: Episode IV - A New Hope", "star-wars-episode-iv-a-new-hope"],
    ["  Spaced   Out  ", "spaced-out"],
    ["Am\u00e9lie", "amlie"],
    ["--Edge--", "edge"],
  ])("turns %j into %j", (title, slug) => {
    expect(slugify(title)).toBe(slug);
  });
});

describe("id slugs", () => {
  it("leads with the id and falls back to it when the title has no URL-safe characters", () => {
    expect(buildIdSlug(42, "The Matrix")).toBe("42-the-matrix");
    expect(buildIdSlug(7, "\u4e03\u4eba\u306e\u4f8d")).toBe("7");
  });

  it("recovers the id an id slug leads with", () => {
    expect(parseIdFromSlug("42-the-matrix")).toBe("42");
    expect(parseIdFromSlug("42")).toBe("42");
    expect(parseIdFromSlug("not-an-id")).toBe("not-an-id");
    expect(parseIdFromSlug(undefined)).toBe("");
  });
});

describe("item slugs", () => {
  it("tells stored items from TMDB titles", () => {
    expect(parseItemSlug(buildIdSlug(42, "The Matrix"))).toEqual({ kind: "item", id: 42 });
    expect(parseItemSlug(buildIdSlug("tmdb-603", "The Matrix"))).toEqual({
      kind: "tmdb",
      tmdbId: 603,
    });
    expect(parseItemSlug("tmdb-603")).toEqual({ kind: "tmdb", tmdbId: 603 });
  });

  it("rejects slugs that name neither", () => {
    expect(parseItemSlug(undefined)).toBeNull();
    expect(parseItemSlug("the-matrix")).toBeNull();
    expect(parseItemSlug("tmdb-")).toBeNull();
  });
});

describe("catalog identity slugs", () => {
  it.each(["tmdb-10", "tvdb-81189", "imdb-tt0078748"])("accepts %s as a catalog identity", (slug) =>
    expect(parseCatalogSlug(slug)).toBe(slug),
  );
  it.each([
    undefined,
    "",
    "10-title",
    "tmdb-10-title",
    "tmdb-0",
    "tvdb--3",
    "imdb-12",
    "../../tmdb-10",
    "tmdb-10/art",
  ])("rejects %s", (slug) => expect(parseCatalogSlug(slug)).toBeNull());
});
