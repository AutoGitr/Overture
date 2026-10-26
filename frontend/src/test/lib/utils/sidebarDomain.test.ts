import { describe, expect, it } from "vitest";
import type { CollectionRead, MediaItemRead } from "../../../generated/rest/types.gen";
import { defaultFilters, type FilterState } from "../../../lib/stores/uiState.svelte";
import {
  CATALOG_FILTER_KEYS,
  catalogStatus,
  defaultCatalogFilters,
  filterCatalogEntries,
  filterSidebarCollections,
  filterSidebarItems,
  hasThemeAttributes,
  hasVisibleActiveFilters,
  metadataIssuesFor,
  normalizeSortPreference,
  preloadRowIndexes,
  searchFieldsFor,
  sortMenu,
  statusTone,
} from "../../../lib/utils/sidebarDomain";
import { catalogRow, collection, mediaItem } from "../../helpers/fixtures";

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
      filterCollections(
        [
          collection({ id: 1, title: "Short Set", theme_duration: 30 }),
          collection({ id: 2, title: "Long Set", theme_duration: 300 }),
          collection({ id: 3, title: "No Theme" }),
        ],
        { filters: withFilters({ themeLength: { min: 120, max: 300 } }) },
      ),
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

function filterCollections(
  collections: CollectionRead[],
  options: Partial<Parameters<typeof filterSidebarCollections>[0]> = {},
): string[] {
  return filterSidebarCollections({
    collections,
    filters: withFilters({}),
    publicDatasetEnabled: false,
    searchQuery: "",
    searchField: "title",
    sortField: "title",
    sortDir: "asc",
    ...options,
  }).map((entry) => entry.title);
}

describe("sidebar collections", () => {
  it("returns an empty collection list when selected libraries do not match", () => {
    expect(
      filterCollections([collection({ id: 1, library_id: "library-1" })], {
        filters: withFilters({ libraryIds: ["library-2"] }),
      }),
    ).toEqual([]);
  });

  it("filters collections by the theme status the backend reports", () => {
    const collections = [
      collection({ id: 1, title: "Themed", theme_status: "complete" }),
      collection({ id: 2, title: "Server Only", has_theme: true, theme_status: "partial" }),
    ];

    expect(
      filterCollections(collections, { filters: withFilters({ theme: "incomplete" }) }),
    ).toEqual(["Server Only"]);
  });

  it("applies the filters collections share with items and ignores item-only ones", () => {
    const collections = [
      collection({ id: 1, title: "Saga 10", art_status: "complete" }),
      collection({ id: 2, title: "Saga 2", art_status: "partial", withheld: true }),
    ];
    expect(
      filterCollections(collections, {
        filters: withFilters({ art: "complete", aspectRatio: "incorrect" }),
      }),
    ).toEqual(["Saga 10"]);
    expect(
      filterCollections(collections, { filters: withFilters({ mediaServer: "missing" }) }),
    ).toEqual(["Saga 2"]);
    expect(filterCollections(collections)).toEqual(["Saga 2", "Saga 10"]);
  });

  it("filters by members, kind, sync status and catalog themes", () => {
    const collections = [
      collection({ id: 1, title: "Manual" }),
      collection({ id: 2, title: "Smart", kind: "smart", managed: true }),
      collection({
        id: 3,
        title: "Failing",
        managed: true,
        sync_failed: true,
        public_dataset_complete: true,
      }),
    ];
    const titles = (filters: Partial<FilterState>, publicDatasetEnabled = false) =>
      filterCollections(collections, { filters: withFilters(filters), publicDatasetEnabled });

    expect(titles({ collectionMembers: "manual" })).toEqual(["Manual"]);
    expect(titles({ collectionMembers: "criteria" })).toEqual(["Failing", "Smart"]);
    expect(titles({ collectionKind: "smart" })).toEqual(["Smart"]);
    expect(titles({ collectionSync: "failed" })).toEqual(["Failing"]);
    expect(titles({ collectionSync: "synced" })).toEqual(["Smart"]);
    expect(titles({ overtureDb: "complete" }, true)).toEqual(["Failing"]);
    expect(titles({ overtureDb: "complete" })).toHaveLength(3);
  });

  it("searches by the chosen field and sorts by the chosen key", () => {
    const collections = [
      collection({
        id: 1,
        title: "Alien",
        collection_group: "Franchises",
        tmdb_collection_id: 8091,
        child_count: 4,
        sort_title: "02_Alien",
      }),
      collection({ id: 2, title: "Batman", child_count: 9, sort_title: "01_Batman" }),
      collection({ id: 3, title: "Cars", youtube_id: "abcdefghijk", child_count: 3 }),
    ];

    expect(filterCollections(collections, { searchField: "group", searchQuery: "franch" })).toEqual(
      ["Alien"],
    );
    expect(
      filterCollections(collections, { searchField: "external_id", searchQuery: "8091" }),
    ).toEqual(["Alien"]);
    expect(
      filterCollections(collections, {
        searchField: "youtube",
        searchQuery: "https://youtu.be/abcdefghijk",
      }),
    ).toEqual(["Cars"]);
    expect(filterCollections(collections, { sortField: "child_count", sortDir: "desc" })).toEqual([
      "Batman",
      "Alien",
      "Cars",
    ]);
    expect(filterCollections(collections, { sortField: "sort_title" })).toEqual([
      "Batman",
      "Alien",
      "Cars",
    ]);
  });

  it("reports only the filters the current mode applies as active", () => {
    const itemOnly = withFilters({
      aspectRatio: "incorrect",
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
    expect(
      hasVisibleActiveFilters(withFilters({ collectionKind: "smart" }), false, "collections"),
    ).toBe(true);
    expect(hasVisibleActiveFilters(withFilters({ collectionKind: "smart" }), false, "items")).toBe(
      false,
    );
    expect(hasVisibleActiveFilters(withFilters({ overtureDb: "complete" }), false, "items")).toBe(
      false,
    );
  });
});

describe("sidebar sort preferences", () => {
  it.each(["library", "collections", "overturedb"] as const)(
    "preserves every %s sort and rejects the others",
    (scope) => {
      for (const { id } of sortMenu(scope)) {
        expect(normalizeSortPreference({ field: id, dir: "desc" }, scope)).toEqual({
          field: id,
          dir: "desc",
        });
      }
      expect(normalizeSortPreference({ field: "child_count", dir: "desc" }, "library").field).toBe(
        "title",
      );
    },
  );

  it.each([null, [], "invalid", {}, { field: 42, dir: "sideways" }])(
    "defaults malformed preferences",
    (value) => {
      expect(normalizeSortPreference(value, "library")).toEqual({ field: "title", dir: "asc" });
    },
  );

  it("offers each list its own sort fields", () => {
    expect(sortMenu("overturedb").map((entry) => entry.id)).toEqual(["title", "year"]);
    expect(sortMenu("collections").map((entry) => entry.id)).toContain("child_count");
    expect(sortMenu("library").map((entry) => entry.id)).not.toContain("child_count");
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

describe("catalog filters", () => {
  const complete = catalogRow({
    title: "Complete",
    media_type: "show",
    tmdb_id: 12,
    poster_url: "poster",
    background_url: "background",
    youtube_id_overturedb: "abcDEF123_4",
    youtube_id_themerrdb: "themerr12345",
    season_posters: 1,
    has_draft: true,
    library_item_id: 2,
  });
  const missing = catalogRow({ title: "Missing", media_type: "show", year: null });
  it.each(CATALOG_FILTER_KEYS)("filters %s by presence in either direction", (key) => {
    const rows = [complete, missing];
    expect(
      filterCatalogEntries({
        entries: rows,
        filters: { ...defaultCatalogFilters(), [key]: "present" },
        searchQuery: "",
      }),
    ).toEqual([complete]);
    expect(
      filterCatalogEntries({
        entries: rows,
        filters: { ...defaultCatalogFilters(), [key]: "missing" },
        searchQuery: "",
      }),
    ).toEqual([missing]);
  });
  it("combines filters, searches IDs and theme links, and keeps unknown years last", () => {
    const filter = (options: Partial<Parameters<typeof filterCatalogEntries>[0]>) =>
      filterCatalogEntries({
        entries: [missing, complete],
        filters: defaultCatalogFilters(),
        searchQuery: "",
        ...options,
      });
    expect(filter({ searchQuery: " COMPLETE " })).toEqual([complete]);
    expect(filter({ searchField: "external_id", searchQuery: "12" })).toEqual([complete]);
    expect(filter({ searchField: "year", searchQuery: "197" })).toEqual([complete]);
    expect(filter({ searchField: "youtube", searchQuery: "https://youtu.be/abcDEF123_4" })).toEqual(
      [complete],
    );
    expect(filter({ sortField: "year", sortDir: "desc" })).toEqual([complete, missing]);
    expect(filter({ sortField: "title", sortDir: "desc" })).toEqual([missing, complete]);
    expect(
      filter({ filters: { ...defaultCatalogFilters(), poster: "present", draft: "missing" } }),
    ).toEqual([]);
  });
  it("counts linked library collections and ignores the season filter for movies", () => {
    const entry = catalogRow({ library_collection_id: 1 });
    expect(
      filterCatalogEntries({
        entries: [entry],
        filters: { ...defaultCatalogFilters(), library: "present", seasonPosters: "missing" },
        searchQuery: "",
      }),
    ).toEqual([entry]);
  });
});
