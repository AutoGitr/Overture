import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  goToCatalog,
  goToCatalogEntry,
  routedCatalogEntry,
  routeScope,
  goToCollection,
  goToCollectionsList,
  goToItem,
  goToItemArt,
  goToItemThemes,
  goToItemView,
  goToLibrary,
  goToSeason,
  goToSeasonsList,
  navigate,
  route,
  routedCollectionId,
  routedItem,
  routedItemId,
  routedItemView,
} from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { appSettings } from "../../helpers/fixtures";

const movie = { id: 42, title: "The Matrix", media_type: "movie" } as const;
const show = { id: 7, title: "Firefly", media_type: "show" } as const;
const tmdbMovie = { tmdb_id: 603, title: "The Matrix", media_type: "movie" } as const;

async function expectPath(pathname: string) {
  await vi.waitFor(() => expect(route.pathname).toBe(pathname));
}

describe("route helpers", () => {
  beforeEach(async () => {
    await navigate("/movies", { replace: true });
  });

  it.each([
    ["movie", "/movies"],
    ["show", "/shows"],
  ] as const)("open the %s library and its collections", async (tab, base) => {
    goToLibrary(tab === "movie" ? "show" : "movie");
    goToLibrary(tab);
    await expectPath(base);

    goToCollectionsList(tab);
    await expectPath(`${base}/collections`);
  });

  it("open a collection by its id and title", async () => {
    goToCollection({ id: 12, title: "Star Wars: Saga", media_type: "show" });
    await expectPath("/shows/collections/12-star-wars-saga");

    goToCollection({ id: 3, title: "Alien", media_type: "movie" });
    await expectPath("/movies/collections/3-alien");
  });

  it("open each detail tab of a stored item", async () => {
    await goToItem(show);
    await expectPath("/shows/7-firefly");

    goToItemArt(show);
    await expectPath("/shows/7-firefly/art/poster");

    goToItemArt(movie, "background");
    await expectPath("/movies/42-the-matrix/art/background");

    goToItemThemes(show);
    await expectPath("/shows/7-firefly/themes");

    goToItemThemes(movie);
    await expectPath("/movies/42-the-matrix/themes");
  });

  it("open a TMDB title that is not stored yet by its TMDB ID", async () => {
    await goToItem(tmdbMovie);

    await expectPath("/movies/tmdb-603-the-matrix");
  });

  it("drill into a season by its number and back out to the season grid", async () => {
    goToSeason(show, { season_num: 0 });
    await expectPath("/shows/7-firefly/art/seasons/0");

    goToSeasonsList(show);
    await expectPath("/shows/7-firefly/art/seasons");

    goToSeason(movie, { season_num: 2 });
    await expectPath("/movies/42-the-matrix/art/seasons/2");
  });

  it.each([
    [{ mode: "themes", artSubTab: "poster", drillSeasonNum: null }, "/shows/7-firefly/themes"],
    [
      { mode: "art", artSubTab: "background", drillSeasonNum: null },
      "/shows/7-firefly/art/background",
    ],
    [{ mode: "art", artSubTab: "seasons", drillSeasonNum: 3 }, "/shows/7-firefly/art/seasons/3"],
  ] as const)("show an item in the view %o", async (view, pathname) => {
    goToItemView(show, view);

    await expectPath(pathname);
  });

  it("replace the current history entry when asked", async () => {
    const replaceState = vi.spyOn(history, "replaceState");
    const pushState = vi.spyOn(history, "pushState");

    await goToItem(movie, { replace: true });
    await expectPath("/movies/42-the-matrix");

    expect(replaceState).toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
  });

  it.each([
    ["/shows/7-firefly", "art", { mode: "art", artSubTab: "poster", drillSeasonNum: null }],
    ["/shows/7-firefly", "themes", { mode: "themes", artSubTab: "poster", drillSeasonNum: null }],
    [
      "/shows/7-firefly/themes",
      "art",
      { mode: "themes", artSubTab: "poster", drillSeasonNum: null },
    ],
    ["/shows/7-firefly/art", "art", { mode: "art", artSubTab: "poster", drillSeasonNum: null }],
    [
      "/shows/7-firefly/art/background",
      "themes",
      { mode: "art", artSubTab: "background", drillSeasonNum: null },
    ],
    [
      "/shows/7-firefly/art/seasons/3",
      "art",
      { mode: "art", artSubTab: "seasons", drillSeasonNum: 3 },
    ],
  ] as const)("read the view of %s with the %s workflow", async (pathname, workflow, view) => {
    settingsState.load(appSettings({ workflow }));
    await navigate(pathname as "/shows");

    expect(routedItemView()).toEqual(view);
    expect(routedItem()).toEqual({ kind: "item", id: 7 });
    expect(routedItemId()).toBe(7);
  });

  it("read what the URL selects", async () => {
    await navigate("/movies/:itemSlug", { params: { itemSlug: "tmdb-603-the-matrix" } });
    expect(routedItem()).toEqual({ kind: "tmdb", tmdbId: 603 });
    expect(routedItemId()).toBeNull();
    expect(routedCollectionId()).toBeNull();

    goToCollection({ id: 12, title: "Action", media_type: "movie" });
    await expectPath("/movies/collections/12-action");
    expect(routedCollectionId()).toBe(12);
    expect(routedItem()).toBeNull();
  });
});

describe("catalog routes", () => {
  it("derives all three sidebar dimensions from the URL", async () => {
    goToCatalog("movie", "collections");
    await expectPath("/overturedb/movies/collections");
    expect(routeScope()).toEqual({ source: "overturedb", tab: "movie", mode: "collections" });
    expect(routedCatalogEntry()).toBeNull();
    goToCatalog("show");
    await expectPath("/overturedb/shows");
    expect(routeScope()).toEqual({ source: "overturedb", tab: "show", mode: "items" });
    goToCatalog("movie");
    await expectPath("/overturedb/movies");
  });
  it.each(["movie", "show", "collection"] as const)(
    "opens %s entries and art and theme tabs",
    async (media_type) => {
      const entry = { media_type, entry_key: "tmdb-10" };
      const base =
        media_type === "collection"
          ? "/overturedb/movies/collections"
          : media_type === "show"
            ? "/overturedb/shows"
            : "/overturedb/movies";
      goToCatalogEntry(entry);
      await expectPath(`${base}/tmdb-10`);
      expect(routedCatalogEntry()).toEqual(entry);
      expect(routedItem()).toBeNull();
      goToCatalogEntry(entry, { mode: "themes", artSubTab: "poster", drillSeasonNum: null });
      await expectPath(`${base}/tmdb-10/themes`);
      goToCatalogEntry(entry, { mode: "art", artSubTab: "background", drillSeasonNum: null });
      await expectPath(`${base}/tmdb-10/art/background`);
    },
  );
  it("drills into catalog season zero and accepts TVDB identities", async () => {
    goToCatalogEntry(
      { media_type: "show", entry_key: "tvdb-81189" },
      { mode: "art", artSubTab: "seasons", drillSeasonNum: 0 },
    );
    await expectPath("/overturedb/shows/tvdb-81189/art/seasons/0");
    expect(routedItemView().drillSeasonNum).toBe(0);
    expect(routedCatalogEntry()?.entry_key).toBe("tvdb-81189");
  });
  it.each([12, 345, 6789])("round-trips database collection ID %s", async (id) => {
    goToCollection({ id, title: "Star Wars", media_type: "movie" });
    await expectPath(`/movies/collections/${id}-star-wars`);
    expect(routedCollectionId()).toBe(id);
  });
});
