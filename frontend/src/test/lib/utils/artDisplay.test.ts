import { describe, expect, it } from "vitest";
import {
  collectionArtDisplayUrl,
  itemArtDisplayUrl,
  itemPosterOriginalUrl,
  seasonPosterUrls,
} from "../../../lib/utils/artDisplay";
import type { MediaItemRead } from "../../../generated/rest/types.gen";
import {
  assetFile,
  collection,
  season as fixtureSeason,
  mediaItem,
  withAsset,
} from "../../helpers/fixtures";

const movie = mediaItem({
  id: 1,
  title: "Alien",
  media_type: "movie",
  folder_path: "/movies/Alien",
  server_item_id: "plex-1",
  assets: {
    poster: { file: assetFile("old-hash"), url: "https://image.test/poster.jpg" },
    background: { file: assetFile("bg-hash"), url: "https://image.test/bg.jpg" },
  },
});

/** *item* with no local files for its poster and background. */
function withoutFiles(item: MediaItemRead): MediaItemRead {
  return withAsset(withAsset(item, "poster", { file: null }), "background", { file: null });
}

describe("art display URLs", () => {
  it("shows local art as its cached display thumbnail and opens the original poster", () => {
    expect(itemArtDisplayUrl(movie, "poster")).toBe(
      "/api/library/items/1/local-image/poster?t=old-hash&size=display",
    );
    expect(itemArtDisplayUrl(movie, "background")).toBe(
      "/api/library/items/1/local-image/background?t=bg-hash&size=display",
    );
    expect(itemPosterOriginalUrl(movie)).toBe("/api/library/items/1/local-image/poster?t=old-hash");
  });

  it("asks the media server for a sized copy when local art is absent", () => {
    const itemWithoutLocal = withoutFiles(movie);
    expect(itemArtDisplayUrl(itemWithoutLocal, "poster")).toBe(
      "/api/library/items/1/provider-art?type=poster&t=0&size=display",
    );
    expect(itemArtDisplayUrl(itemWithoutLocal, "background")).toBe(
      "/api/library/items/1/provider-art?type=background&t=0&size=display",
    );
    expect(itemPosterOriginalUrl(itemWithoutLocal)).toBe(
      "/api/library/items/1/provider-art?type=poster&t=0",
    );
    expect(itemPosterOriginalUrl(null)).toBeNull();
  });

  it("returns null instead of remote URLs when neither local nor server art exists", () => {
    const unmanagedItem = { ...withoutFiles(movie), copies: [] };
    expect(itemArtDisplayUrl(unmanagedItem, "poster")).toBeNull();
    expect(itemArtDisplayUrl(unmanagedItem, "background")).toBeNull();
  });

  it("shows the chosen links of an item without a folder", () => {
    const chosen = withAsset({ ...withoutFiles(movie), folder_path: null, copies: [] }, "poster", {
      preview_url: "https://image.test/poster-small.jpg",
    });
    // Shown by its preview everywhere, as a search result shows it; opened in full.
    expect(itemArtDisplayUrl(chosen, "poster")).toBe("https://image.test/poster-small.jpg");
    expect(itemPosterOriginalUrl(chosen)).toBe("https://image.test/poster.jpg");
    expect(itemArtDisplayUrl(withAsset(chosen, "poster", { preview_url: null }), "poster")).toBe(
      "https://image.test/poster.jpg",
    );
    expect(itemArtDisplayUrl(chosen, "background")).toBe("https://image.test/bg.jpg");
    expect(
      seasonPosterUrls(
        chosen,
        fixtureSeason({ poster: { url: "https://image.test/s.jpg", preview_url: null } }),
      ),
    ).toEqual({ src: "https://image.test/s.jpg", fallbackSrc: null });
  });

  it("resolves season art locally, then provider, then null (never remote)", () => {
    const show = { ...movie, id: 2, media_type: "show" as const };

    // 1. Local season poster (local as primary, server as fallback)
    const localSeason = fixtureSeason({
      id: 20,
      media_item_id: show.id,
      season_num: 1,
      poster: { file: assetFile("season-hash"), url: "https://image.test/season.jpg" },
    });
    const localUrls = seasonPosterUrls(show, localSeason);
    expect(localUrls.src).toBe("/api/library/seasons/20/local-image?t=season-hash&size=display");
    expect(localUrls.fallbackSrc).toBe(
      "/api/library/seasons/20/provider-art?t=season-hash&size=display",
    );

    // 2. Provider art fallback when local season poster is absent (server as primary, no fallback)
    const providerSeason = fixtureSeason({
      id: 21,
      media_item_id: show.id,
      season_num: 2,
      poster: { file: null, url: "https://image.test/season.jpg" },
    });
    const providerUrls = seasonPosterUrls(show, providerSeason);
    expect(providerUrls.src).toContain("/api/library/seasons/21/provider-art");
    expect(providerUrls.fallbackSrc).toBeNull();

    // 3. Null when neither exists (never remote URL): no server holds the show
    const unmanagedSeason = fixtureSeason({
      id: 22,
      media_item_id: show.id,
      season_num: 3,
      poster: { file: null, url: "https://image.test/season.jpg" },
    });
    const unmanagedUrls = seasonPosterUrls({ ...show, copies: [] }, unmanagedSeason);
    expect(unmanagedUrls.src).toBeNull();
    expect(unmanagedUrls.fallbackSrc).toBeNull();
    expect(seasonPosterUrls(null, localSeason)).toEqual({ src: null, fallbackSrc: null });
  });

  it("shows a collection's uploaded image from the cache, else the server's copy", () => {
    const uploaded = collection({
      id: 7,
      server_poster_version: "v1",
      server_background_version: "v2",
      assets: { poster: { content_hash: "a".repeat(64) } },
    });
    expect(collectionArtDisplayUrl(uploaded, "poster")).toBe(
      `/api/collections/7/local-image/poster?t=${"a".repeat(64)}&size=display`,
    );
    expect(collectionArtDisplayUrl(uploaded, "background")).toBe(
      "/api/collections/7/image/background?t=v2&size=display",
    );
    expect(
      collectionArtDisplayUrl(collection({ server_poster_version: null }), "poster"),
    ).toBeNull();
    // A season's file shows like an item's, whether or not its show has a folder.
    expect(
      seasonPosterUrls(
        { ...movie, media_type: "show", folder_path: null },
        fixtureSeason({ id: 9, poster: { file: assetFile("season-hash") } }),
      ).src,
    ).toBe("/api/library/seasons/9/local-image?t=season-hash&size=display");
    expect(collectionArtDisplayUrl(null, "poster")).toBeNull();
  });
});
