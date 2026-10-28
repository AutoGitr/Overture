import { describe, expect, it } from "vitest";

import {
  type DetailSubject,
  buildImdbUrl,
  buildPosterDbUrl,
  buildTmdbUrl,
  buildTvdbUrl,
} from "../../../lib/utils/externalLinks";
import { mediaItem, season as fixtureSeason } from "../../helpers/fixtures";

const item = mediaItem({ id: 1, title: "Show", media_type: "show", tmdb_id: 117648 });
const season = fixtureSeason({ id: 10, media_item_id: 1, season_num: 2 });

describe("buildTmdbUrl", () => {
  it.each([
    ["poster", "posters"],
    ["background", "backdrops"],
  ])("opens collection %s artwork directly", (artType, section) => {
    const collection: DetailSubject = {
      title: "Saga",
      year: null,
      media_type: "collection",
      tmdb_id: 10,
      tvdb_id: null,
      imdb_id: null,
    };
    expect(buildTmdbUrl(collection, "art", artType, null)).toBe(
      `https://www.themoviedb.org/collection/10/images/${section}`,
    );
    expect(buildTmdbUrl(collection, "themes", artType, null)).toBe(
      "https://www.themoviedb.org/collection/10",
    );
  });

  it("keeps the season grid on the item page until drill-down", () => {
    expect(buildTmdbUrl(item, "art", "seasons", null)).toBe("https://www.themoviedb.org/tv/117648");
  });

  it("uses season-specific links after drill-down", () => {
    expect(buildTmdbUrl(item, "art", "season_poster", season)).toBe(
      "https://www.themoviedb.org/tv/117648/season/2/images/posters",
    );
  });
});

describe("site links", () => {
  const movie = mediaItem({
    id: 2,
    title: "The Matrix",
    media_type: "movie",
    tmdb_id: 603,
    tvdb_id: 169,
  });

  it("names movies and shows the way each site does", () => {
    expect(buildTvdbUrl(movie)).toBe("https://thetvdb.com/movies/the-matrix");
    expect(buildPosterDbUrl(item)).toBe("https://theposterdb.com/search?term=Show&section=shows");
    expect(buildImdbUrl("tt0133093")).toBe("https://www.imdb.com/title/tt0133093/");
  });
});
