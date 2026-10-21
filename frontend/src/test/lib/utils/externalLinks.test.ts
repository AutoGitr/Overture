import { describe, expect, it } from "vitest";

import {
  buildFanartUrl,
  buildImdbUrl,
  buildLetterboxdUrl,
  buildPosterDbUrl,
  buildTmdbUrl,
  buildTvdbUrl,
} from "../../../lib/utils/externalLinks";
import { mediaItem, season as fixtureSeason } from "../../helpers/fixtures";

const item = mediaItem({ id: 1, title: "Show", media_type: "show", tmdb_id: 117648 });
const season = fixtureSeason({ id: 10, media_item_id: 1, season_num: 2 });

describe("buildTmdbUrl", () => {
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

  it("opens fanart.tv on the section of the art being chosen", () => {
    expect(buildFanartUrl(movie, "art", "background")).toBe(
      "https://fanart.tv/movie/603/the-matrix/?section=wallpaper",
    );
    expect(buildFanartUrl(movie, "themes", "poster")).toBe(
      "https://fanart.tv/movie/603/the-matrix/",
    );
    expect(buildFanartUrl(mediaItem({ media_type: "show", tvdb_id: null }), "art", "poster")).toBe(
      null,
    );
  });

  it("names movies and shows the way each site does", () => {
    expect(buildTvdbUrl(movie)).toBe("https://thetvdb.com/movies/the-matrix");
    expect(buildLetterboxdUrl(movie)).toBe("https://letterboxd.com/film/the-matrix/");
    expect(buildLetterboxdUrl(item)).toBeNull();
    expect(buildPosterDbUrl(item)).toBe("https://theposterdb.com/search?term=Show&section=shows");
    expect(buildImdbUrl("tt0133093")).toBe("https://www.imdb.com/title/tt0133093/");
  });
});
