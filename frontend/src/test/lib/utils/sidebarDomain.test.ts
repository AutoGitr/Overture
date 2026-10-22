import { describe, expect, it } from "vitest";
import type { MediaItemRead } from "../../../generated/rest/types.gen";
import { defaultFilters, type FilterState } from "../../../lib/stores/uiState.svelte";
import {
  filterSidebarCollections,
  filterSidebarItems,
  hasThemeAttributes,
  hasVisibleActiveFilters,
  metadataIssuesFor,
  normalizeSortPreference,
  preloadRowIndexes,
  searchFieldsFor,
  SIDEBAR_SORT_FIELDS,
  statusTone,
} from "../../../lib/utils/sidebarDomain";
import { collection, mediaItem } from "../../helpers/fixtures";

function withFilters(patch: Partial<FilterState>): FilterState {
  return { ...defaultFilters(), ...patch };
}

function filterItems(
  items: MediaItemRead[],
  options: Partial<Parameters<typeof filterSidebarItems>[0]> = {},
): string[] {
  return filterSidebarItems({
    items,
    filters: defaultFilters(),
    publicDatasetEnabled: false,
    searchQuery: "",
    searchField: "title",
    sortField: "title",
    sortDir: "asc",
    ...options,
  }).map((item) => item.title);
}

describe("sidebar domain helpers", () => {
  it("shows the backend's asset status as a tone, or downloading while a job runs", () => {
    expect(statusTone("complete", false)).toBe("success");
    expect(statusTone("partial", false)).toBe("warning");
    expect(statusTone("missing", false)).toBe("danger");
    expect(statusTone("complete", true)).toBe("downloading");
  });

  it("detects theme attributes presence independently of local files", () => {
    expect(hasThemeAttributes(null)).toBe(false);
    expect(hasThemeAttributes(undefined)).toBe(false);
    expect(
      hasThemeAttributes(
        mediaItem({
          theme_file_hash: "theme-hash",
          youtube_id: null,
          youtube_title: null,
          youtube_duration: null,
        }),
      ),
    ).toBe(false);
    expect(hasThemeAttributes(mediaItem({ youtube_id: "abcDEF123_4" }))).toBe(true);
    expect(hasThemeAttributes(mediaItem({ youtube_title: "Theme Song" }))).toBe(true);
    expect(hasThemeAttributes(mediaItem({ youtube_duration: 120 }))).toBe(true);
  });
});

describe("sidebar item filters", () => {
  it("finds catalog ID mismatches only while OvertureDB is enabled", () => {
    const items = [
      mediaItem({ title: "Mismatch", public_dataset_ids: "mismatching" }),
      mediaItem({ id: 2, title: "Match", public_dataset_ids: "matching", tmdb_id: 1 }),
      mediaItem({ id: 3, title: "Uncatalogued" }),
    ];
    const filters = withFilters({ metadataIssues: { flags: ["id_mismatch"], mode: "all" } });
    expect(filterItems(items, { filters, publicDatasetEnabled: true })).toEqual(["Mismatch"]);
    expect(
      filterItems(items, {
        filters: withFilters({
          metadataIssues: { flags: ["id_mismatch", "no_tmdb_id"], mode: "any" },
        }),
        publicDatasetEnabled: true,
      }),
    ).toEqual(["Mismatch", "Uncatalogued"]);
    expect(filterItems(items, { filters })).toEqual(["Match", "Mismatch", "Uncatalogued"]);
    expect(hasVisibleActiveFilters(filters, true, "items")).toBe(true);
    expect(hasVisibleActiveFilters(filters, false, "items")).toBe(false);
    expect(hasVisibleActiveFilters(filters, true, "collections")).toBe(false);
  });

  it("filters art and theme completion by the status the backend reports", () => {
    const complete = mediaItem({
      id: 1,
      title: "Complete",
      art_status: "complete",
      theme_status: "complete",
    });
    const incomplete = mediaItem({
      id: 2,
      title: "Incomplete",
      art_status: "partial",
      theme_status: "partial",
    });

    expect(
      filterItems([incomplete, complete], { filters: withFilters({ art: "complete" }) }),
    ).toEqual(["Complete"]);
    expect(
      filterItems([incomplete, complete], { filters: withFilters({ theme: "incomplete" }) }),
    ).toEqual(["Incomplete"]);
  });

  it("filters aspect ratio by the flag the backend computes for the tolerance setting", () => {
    const items = [
      mediaItem({ id: 1, title: "Misshapen", has_incorrect_aspect_ratio: true }),
      mediaItem({ id: 2, title: "Fine" }),
    ];

    expect(filterItems(items, { filters: withFilters({ aspectRatio: "incorrect" }) })).toEqual([
      "Misshapen",
    ]);
    expect(filterItems(items, { filters: withFilters({ aspectRatio: "correct" }) })).toEqual([
      "Fine",
    ]);
  });

  it("filters resolution by an inclusive width range and hides unmeasured artwork", () => {
    const items = [
      mediaItem({ id: 1, title: "Large", poster_width: 2000, background_width: 1280 }),
      mediaItem({ id: 2, title: "Medium", poster_width: 1000, background_width: 3840 }),
      mediaItem({ id: 3, title: "Small", poster_width: 500 }),
      mediaItem({ id: 4, title: "Unmeasured" }),
    ];
    const resolution = (patch: Partial<FilterState["resolution"]>) =>
      withFilters({ resolution: { artType: "poster", min: null, max: null, ...patch } });

    expect(filterItems(items)).toHaveLength(4);
    expect(filterItems(items, { filters: resolution({ min: 1000 }) })).toEqual(["Large", "Medium"]);
    expect(filterItems(items, { filters: resolution({ max: 1000 }) })).toEqual(["Medium", "Small"]);
    expect(filterItems(items, { filters: resolution({ min: 600, max: 1999 }) })).toEqual([
      "Medium",
    ]);
    expect(
      filterItems(items, { filters: resolution({ artType: "background", min: 1920 }) }),
    ).toEqual(["Medium"]);
  });

  it("filters items and collections by an inclusive theme length range", () => {
    const items = [
      mediaItem({ id: 1, title: "Short", theme_duration: 45 }),
      mediaItem({ id: 2, title: "Long", theme_duration: 240, youtube_duration: 30 }),
      mediaItem({ id: 3, title: "Unknown" }),
    ];

    expect(
      filterItems(items, { filters: withFilters({ themeLength: { min: 120, max: null } }) }),
    ).toEqual(["Long"]);
    expect(
      filterItems(items, { filters: withFilters({ themeLength: { min: null, max: 45 } }) }),
    ).toEqual(["Short"]);
    expect(filterItems(items)).toEqual(["Long", "Short", "Unknown"]);
    expect(
      filterSidebarCollections({
        collections: [
          collection({ id: "c1", title: "Short Set", youtube_duration: 30 }),
          collection({ id: "c2", title: "Long Set", youtube_duration: 300 }),
          collection({ id: "c3", title: "No Theme" }),
        ],
        filters: withFilters({ themeLength: { min: 120, max: 300 } }),
        searchQuery: "",
      }).map((entry) => entry.title),
    ).toEqual(["Long Set"]);
  });

  it("filters by any selected theme source", () => {
    const items = [
      mediaItem({ id: 1, title: "Downloaded", youtube_id_source: "download" }),
      mediaItem({ id: 2, title: "Tagged", youtube_id_source: "embedded_id" }),
      mediaItem({ id: 3, title: "Linked", youtube_id_source: "metadata_url" }),
      mediaItem({ id: 4, title: "No Theme" }),
    ];

    expect(
      filterItems(items, { filters: withFilters({ themeSources: ["embedded_id", "download"] }) }),
    ).toEqual(["Downloaded", "Tagged"]);
  });

  it("filters by any selected art source of the chosen artwork", () => {
    const items = [
      mediaItem({
        id: 1,
        title: "Curated",
        poster_source: "overturedb",
        background_source: "tmdb",
      }),
      mediaItem({ id: 2, title: "Fan Art", poster_source: "tmdb", background_source: "fanart" }),
      mediaItem({ id: 3, title: "Poster DB", poster_source: "tpdb" }),
      mediaItem({ id: 4, title: "No Art" }),
    ];
    const bySource = (artType: "any" | "poster" | "background", sources: string[]) =>
      filterItems(items, {
        filters: withFilters({
          artSource: { artType, sources: sources as FilterState["artSource"]["sources"] },
        }),
      });

    expect(bySource("any", [])).toEqual(["Curated", "Fan Art", "No Art", "Poster DB"]);
    expect(bySource("any", ["tmdb"])).toEqual(["Curated", "Fan Art"]);
    expect(bySource("poster", ["tmdb"])).toEqual(["Fan Art"]);
    expect(bySource("background", ["tmdb", "fanart"])).toEqual(["Curated", "Fan Art"]);
    expect(bySource("poster", ["overturedb", "tpdb"])).toEqual(["Curated", "Poster DB"]);
  });

  it("filters items by themerrdb status only while the public dataset is enabled", () => {
    const items = [
      mediaItem({ id: 1, title: "Theme Match", public_dataset_themerrdb: true }),
      mediaItem({ id: 2, title: "No Theme", public_dataset_themerrdb: false }),
    ];

    expect(
      filterItems(items, {
        filters: withFilters({ themerrDb: "complete" }),
        publicDatasetEnabled: true,
      }),
    ).toEqual(["Theme Match"]);
    expect(
      filterItems(items, {
        filters: withFilters({ themerrDb: "incomplete" }),
        publicDatasetEnabled: true,
      }),
    ).toEqual(["No Theme"]);
    expect(filterItems(items, { filters: withFilters({ themerrDb: "complete" }) })).toHaveLength(2);
  });

  it("filters items by whether they are linked to a media server item", () => {
    // Items the server removed are never listed, so only unlinked items are missing.
    const items = [
      mediaItem({ id: 1, title: "Present", server_item_id: "srv-1" }),
      mediaItem({ id: 2, title: "No Server ID", server_item_id: null }),
    ];

    expect(filterItems(items, { filters: withFilters({ mediaServer: "present" }) })).toEqual([
      "Present",
    ]);
    expect(filterItems(items, { filters: withFilters({ mediaServer: "missing" }) })).toEqual([
      "No Server ID",
    ]);
  });

  it("filters items by missing metadata with any and all match modes", () => {
    const items = [
      mediaItem({
        id: 1,
        title: "Missing Both",
        tmdb_id: null,
        imdb_id: null,
        folder_path: "/m/1",
      }),
      mediaItem({
        id: 2,
        title: "Missing TMDB",
        tmdb_id: null,
        imdb_id: "tt123",
        folder_path: "/m/2",
      }),
      mediaItem({
        id: 3,
        title: "Missing None",
        tmdb_id: 456,
        imdb_id: "tt123",
        folder_path: "/m/3",
      }),
      mediaItem({ id: 4, title: "No Path", tmdb_id: 7, imdb_id: "tt7", folder_path: null }),
    ];
    const metadataIssues = (mode: "all" | "any") =>
      withFilters({ metadataIssues: { flags: ["no_tmdb_id", "no_imdb_id"], mode } });

    expect(filterItems(items, { filters: metadataIssues("all") })).toEqual(["Missing Both"]);
    expect(filterItems(items, { filters: metadataIssues("any") })).toEqual([
      "Missing Both",
      "Missing TMDB",
    ]);
    expect(
      filterItems(items, {
        filters: withFilters({ metadataIssues: { flags: ["no_local_path"], mode: "all" } }),
      }),
    ).toEqual(["No Path"]);
  });

  it("offers TVDB IDs and the director search only where they apply", () => {
    expect(metadataIssuesFor("movie", true)).not.toContain("no_tvdb_id");
    expect(metadataIssuesFor("show", true)).toContain("no_tvdb_id");
    expect(metadataIssuesFor("movie", true)).toContain("id_mismatch");
    expect(metadataIssuesFor("movie", false)).not.toContain("id_mismatch");
    expect(searchFieldsFor("movie", false)).toContain("director");
    expect(searchFieldsFor("show", false)).not.toContain("director");
    expect(searchFieldsFor("show", false)).not.toContain("tmdb");
    expect(searchFieldsFor("show", true)).toContain("tmdb");
  });
});

describe("sidebar search", () => {
  it("searches directors on movies only", () => {
    const items = [
      mediaItem({ id: 1, title: "12 Monkeys", media_type: "movie", director: "Terry Gilliam" }),
      mediaItem({ id: 2, title: "Alien", media_type: "movie", director: "Ridley Scott" }),
      mediaItem({ id: 3, title: "Monty Python", media_type: "show", director: "Terry Gilliam" }),
    ];

    expect(filterItems(items, { searchQuery: "Gilliam", searchField: "director" })).toEqual([
      "12 Monkeys",
    ]);
  });

  it("matches TMDB, TVDB and IMDb IDs exactly, including pasted IMDb links", () => {
    const items = [
      mediaItem({ id: 1, title: "Matrix", tmdb_id: 603, imdb_id: "tt0133093" }),
      mediaItem({ id: 2, title: "Lost", tmdb_id: 4607, tvdb_id: 73739, imdb_id: null }),
      mediaItem({ id: 3, title: "Unknown", tmdb_id: null, tvdb_id: null, imdb_id: null }),
    ];
    const search = (searchQuery: string) =>
      filterItems(items, { searchQuery, searchField: "external_id" });

    expect(search("603")).toEqual(["Matrix"]);
    expect(search("60")).toEqual([]);
    expect(search("73739")).toEqual(["Lost"]);
    expect(search("TT0133093")).toEqual(["Matrix"]);
    expect(search("https://www.imdb.com/title/tt0133093/")).toEqual(["Matrix"]);
    expect(search("null")).toEqual([]);
  });

  it("matches YouTube links and IDs exactly and titles by substring", () => {
    const items = [
      mediaItem({
        id: 1,
        title: "Jaws",
        youtube_id: "abcDEF123_4",
        youtube_title: "Jaws Main Title",
      }),
      mediaItem({ id: 2, title: "Alien", youtube_id: "zyxWVU987_6", youtube_title: "Alien OST" }),
    ];
    const search = (searchQuery: string) =>
      filterItems(items, { searchQuery, searchField: "youtube" });

    expect(search("https://www.youtube.com/watch?v=abcDEF123_4")).toEqual(["Jaws"]);
    expect(search("https://youtu.be/zyxWVU987_6")).toEqual(["Alien"]);
    expect(search("abcdef123_4")).toEqual(["Jaws"]);
    expect(search("ost")).toEqual(["Alien"]);
  });
});

describe("sidebar sorting", () => {
  it("keeps items without a value last in both directions and breaks ties by title", () => {
    const items = [
      mediaItem({ id: 1, title: "Missing B" }),
      mediaItem({ id: 2, title: "Old", year: 1980 }),
      mediaItem({ id: 3, title: "Missing A" }),
      mediaItem({ id: 4, title: "Tie B", year: 2000 }),
      mediaItem({ id: 5, title: "Tie A", year: 2000 }),
    ];

    expect(filterItems(items, { sortField: "year", sortDir: "asc" })).toEqual([
      "Old",
      "Tie A",
      "Tie B",
      "Missing A",
      "Missing B",
    ]);
    expect(filterItems(items, { sortField: "year", sortDir: "desc" })).toEqual([
      "Tie A",
      "Tie B",
      "Old",
      "Missing A",
      "Missing B",
    ]);
  });

  it("sorts titles with numeric, case-insensitive collation", () => {
    const items = [
      mediaItem({ id: 1, title: "Part 10" }),
      mediaItem({ id: 2, title: "part 2" }),
      mediaItem({ id: 3, title: "Part 1" }),
    ];

    expect(filterItems(items)).toEqual(["Part 1", "part 2", "Part 10"]);
    expect(filterItems(items, { sortDir: "desc" })).toEqual(["Part 10", "part 2", "Part 1"]);
  });

  it.each([
    ["poster_resolution", { poster_width: 1000 }, { poster_width: 2000 }],
    ["background_resolution", { background_width: 1280 }, { background_width: 3840 }],
    ["theme_length", { theme_duration: 30 }, { theme_duration: 200 }],
    [
      "last_synced_at",
      { last_synced_at: "2026-01-01T00:00:00Z" },
      { last_synced_at: "2026-05-01T00:00:00Z" },
    ],
    [
      "last_matched_at",
      { last_matched_at: "2025-12-31T23:00:00Z" },
      { last_matched_at: "2026-01-01T00:00:00Z" },
    ],
    [
      "server_added_at",
      { server_added_at: "2024-01-01T00:00:00Z" },
      { server_added_at: "2025-01-01T00:00:00Z" },
    ],
  ] as const)("sorts by %s", (sortField, lower, higher) => {
    const items = [
      mediaItem({ id: 1, title: "Lower", ...lower }),
      mediaItem({ id: 2, title: "Unset" }),
      mediaItem({ id: 3, title: "Higher", ...higher }),
    ];

    expect(filterItems(items, { sortField, sortDir: "desc" })).toEqual([
      "Higher",
      "Lower",
      "Unset",
    ]);
    expect(filterItems(items, { sortField, sortDir: "asc" })).toEqual(["Lower", "Higher", "Unset"]);
  });
});

describe("sidebar collections", () => {
  it("returns an empty collection list when selected libraries do not match", () => {
    expect(
      filterSidebarCollections({
        collections: [collection({ id: "collection-1", library_id: "library-1" })],
        filters: withFilters({ libraryIds: ["library-2"] }),
        searchQuery: "",
      }),
    ).toEqual([]);
  });

  it("filters collections by the theme status the backend reports", () => {
    const collections = [
      collection({ id: "c1", title: "Themed", theme_status: "complete" }),
      collection({ id: "c2", title: "Server Only", has_theme: true, theme_status: "partial" }),
    ];

    expect(
      filterSidebarCollections({
        collections,
        filters: withFilters({ theme: "incomplete" }),
        searchQuery: "",
      }).map((entry) => entry.title),
    ).toEqual(["Server Only"]);
  });

  it("sorts by title and ignores item-only filters", () => {
    expect(
      filterSidebarCollections({
        collections: [
          collection({ id: "c1", title: "Saga 10" }),
          collection({ id: "c2", title: "Saga 2" }),
        ],
        filters: withFilters({ art: "complete", aspectRatio: "incorrect" }),
        searchQuery: "",
      }).map((entry) => entry.title),
    ).toEqual(["Saga 2", "Saga 10"]);
  });

  it("reports only the filters the current mode applies as active", () => {
    const itemOnly = withFilters({
      art: "complete",
      resolution: { artType: "poster", min: 1, max: null },
    });
    const shared = withFilters({ themeLength: { min: 60, max: null } });

    expect(hasVisibleActiveFilters(itemOnly, false, "items")).toBe(true);
    expect(hasVisibleActiveFilters(itemOnly, false, "collections")).toBe(false);
    expect(
      hasVisibleActiveFilters(
        withFilters({ artSource: { artType: "any", sources: ["tpdb"] } }),
        false,
        "items",
      ),
    ).toBe(true);
    expect(hasVisibleActiveFilters(shared, false, "collections")).toBe(true);
    expect(hasVisibleActiveFilters(withFilters({ overtureDb: "complete" }), false, "items")).toBe(
      false,
    );
  });
});

describe("sidebar sort preferences", () => {
  it.each(SIDEBAR_SORT_FIELDS)("preserves the supported %s sort", (field) => {
    expect(normalizeSortPreference({ field, dir: "desc" })).toEqual({ field, dir: "desc" });
  });

  it.each([null, [], "invalid", {}, { field: 42, dir: "sideways" }])(
    "defaults malformed preferences",
    (value) => {
      expect(normalizeSortPreference(value)).toEqual({ field: "title", dir: "asc" });
    },
  );
});

describe("sidebar thumbnail preloading", () => {
  it("covers one screen past the mounted rows, below first, nearest first", () => {
    // Rows 100-109 on screen, so rows 92-117 are mounted (8 overscan each way).
    expect(preloadRowIndexes(100, 110, 1000)).toEqual([
      118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 91, 90, 89, 88, 87, 86, 85, 84, 83, 82,
    ]);
  });

  it("stays inside the list", () => {
    expect(preloadRowIndexes(0, 10, 25)).toEqual([18, 19, 20, 21, 22, 23, 24]);
    expect(preloadRowIndexes(0, 0, 0)).toEqual([]);
  });
});
