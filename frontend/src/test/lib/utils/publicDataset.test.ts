import { describe, expect, it } from "vitest";
import type { MediaItemRead, PublicDatasetRecordItem } from "../../../generated/rest/types.gen";
import {
  buildContributionIssueUrl,
  hasContributionValues,
  selectionMatchesPublicDataset,
} from "../../../lib/utils/publicDataset";
import {
  season as fixtureSeason,
  mediaItem,
  catalogEntry,
  publicDatasetRecord,
  publicDatasetRecordItem,
  publicDatasetRecordSeason,
} from "../../helpers/fixtures";

const REPO_URL = "https://github.com/AutoGitr/OvertureDB";

const movie = mediaItem({
  id: 1,
  title: "Alien",
  media_type: "movie",
  year: 1979,
  tmdb_id: 348,
  tvdb_id: null,
  imdb_id: "tt0078748",
  poster_url: "https://image.test/poster.jpg",
  background_url: "",
  youtube_id: "abc123",
});

function withAssetValues(
  item: MediaItemRead,
  posterUrl: string | null,
  youtubeId: string | null,
): MediaItemRead {
  return {
    ...item,
    poster_url: posterUrl,
    youtube_id: youtubeId,
  };
}

function matchingPublicDatasetRecord(
  item: MediaItemRead,
  itemOverrides: Partial<PublicDatasetRecordItem> = {},
) {
  return publicDatasetRecord({
    item: publicDatasetRecordItem({
      background_url: item.background_url,
      media_type: item.media_type,
      poster_url: item.poster_url,
      youtube_id_overturedb: item.youtube_id,
      youtube_id_themerrdb: null,
      ...itemOverrides,
    }),
  });
}

describe("public dataset helpers", () => {
  it("detects contribution values on item and season art", () => {
    expect(hasContributionValues(null)).toBe(false);
    expect(hasContributionValues(withAssetValues(movie, "", ""))).toBe(false);
    expect(hasContributionValues(movie)).toBe(true);
    expect(
      hasContributionValues({ ...withAssetValues(movie, "", ""), media_type: "show" }, [
        fixtureSeason({
          id: 7,
          season_num: 1,
          title: "Season 1",
          poster_url: "https://image.test/s1.jpg",
        }),
      ]),
    ).toBe(true);
  });

  it("builds movie issue URLs with encoded metadata fields", () => {
    const url = new URL(buildContributionIssueUrl(REPO_URL, movie));
    expect(url.origin + url.pathname).toBe("https://github.com/AutoGitr/OvertureDB/issues/new");
    expect(url.searchParams.get("template")).toBe("movie.yml");
    expect(url.searchParams.get("title")).toBe("[Movie]: Alien (1979)");
    expect(url.searchParams.get("item_title")).toBe("Alien");
    expect(url.searchParams.get("year")).toBe("1979");
    expect(url.searchParams.get("tmdb_id")).toBe("348");
    expect(url.searchParams.get("imdb_id")).toBe("tt0078748");
    expect(url.searchParams.get("poster_url")).toBe("https://image.test/poster.jpg");
    expect(url.searchParams.get("youtube_id")).toBe("abc123");
    expect(url.searchParams.has("modification_reason")).toBe(false);
  });

  it("builds show issue URLs with formatted season poster blocks", () => {
    const show: MediaItemRead = {
      ...movie,
      media_type: "show",
      title: "Twin Peaks",
      year: 1990,
    };
    const url = new URL(
      buildContributionIssueUrl(REPO_URL, show, [
        fixtureSeason({
          id: 7,
          season_num: 1,
          title: "Season 1",
          poster_url: "https://image.test/s1.jpg",
        }),
      ]),
    );
    expect(url.searchParams.get("template")).toBe("show.yml");
    expect(url.searchParams.get("title")).toBe("[Show]: Twin Peaks (1990)");
    expect(url.searchParams.get("season_posters")).toBe("1=https://image.test/s1.jpg");
    expect(url.searchParams.has("modification_reason")).toBe(false);
  });

  it("detects when the local contribution already matches OvertureDB", () => {
    expect(selectionMatchesPublicDataset(movie, [], matchingPublicDatasetRecord(movie))).toBe(true);

    // Also matches if it matches themerrdb
    expect(
      selectionMatchesPublicDataset(
        movie,
        [],
        matchingPublicDatasetRecord(movie, {
          youtube_id_overturedb: null,
          youtube_id_themerrdb: movie.youtube_id,
        }),
      ),
    ).toBe(true);

    expect(
      selectionMatchesPublicDataset(
        movie,
        [],
        matchingPublicDatasetRecord(movie, { poster_url: "https://image.test/other.jpg" }),
      ),
    ).toBe(false);

    expect(
      selectionMatchesPublicDataset(
        movie,
        [],
        matchingPublicDatasetRecord(movie, {
          youtube_id_overturedb: "different1",
          youtube_id_themerrdb: "different2",
        }),
      ),
    ).toBe(false);
  });

  it("requires local season posters to match OvertureDB season records", () => {
    const show: MediaItemRead = { ...movie, media_type: "show" };
    const seasons = [
      fixtureSeason({
        id: 7,
        season_num: 1,
        title: "Season 1",
        poster_url: "https://image.test/s1.jpg",
      }),
    ];

    expect(
      selectionMatchesPublicDataset(show, seasons, {
        ...matchingPublicDatasetRecord(show),
        seasons: [
          publicDatasetRecordSeason({
            id: 1,
            public_dataset_item_id: 1,
            season_num: 1,
            poster_url: "https://image.test/s1.jpg",
          }),
        ],
      }),
    ).toBe(true);

    expect(selectionMatchesPublicDataset(show, seasons, matchingPublicDatasetRecord(show))).toBe(
      false,
    );
  });
});

describe("catalog contributions", () => {
  it("uses the collection template and draft theme with no year", () => {
    const entry = catalogEntry({
      media_type: "collection",
      title: "Star Wars",
      tmdb_id: 10,
      year: null,
      youtube_id_overturedb: "abcDEF123_4",
    });
    const params = new URL(buildContributionIssueUrl(REPO_URL, entry)).searchParams;
    expect(params.get("template")).toBe("collection.yml");
    expect(params.get("title")).toBe("[Collection]: Star Wars");
    expect(params.get("tmdb_id")).toBe("10");
    expect(params.get("youtube_id")).toBe("abcDEF123_4");
  });
  it("includes a catalog show's season posters", () => {
    const params = new URL(
      buildContributionIssueUrl(
        REPO_URL,
        catalogEntry({
          media_type: "show",
          seasons: [{ season_num: 0, poster_url: "https://image.test/zero.jpg" }],
        }),
      ),
    ).searchParams;
    expect(params.get("template")).toBe("show.yml");
    expect(params.get("season_posters")).toBe("0=https://image.test/zero.jpg");
  });
});
