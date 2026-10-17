import { beforeEach, describe, expect, it, vi } from "vitest";
import {
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
} from "../../../lib/router/routes";

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
    goToCollection({ id: "12", title: "Star Wars: Saga", media_type: "show" });
    await expectPath("/shows/collections/12-star-wars-saga");

    goToCollection({ id: "3", title: "Alien", media_type: "movie" });
    await expectPath("/movies/collections/3-alien");
  });

  it("open each detail tab of a stored item", async () => {
    goToItem(show);
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
    goToItem(tmdbMovie);

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
    [{ mode: "database", artSubTab: "poster", drillSeasonNum: null }, "/shows/7-firefly"],
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

    goToItem(movie, { replace: true });
    await expectPath("/movies/42-the-matrix");

    expect(replaceState).toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
  });
});
