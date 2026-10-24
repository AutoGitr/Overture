import { describe, expect, it } from "vitest";
import {
  collectionImageUrl,
  itemArtDisplayUrl,
  itemPosterOriginalUrl,
  seasonPosterUrls,
} from "../../../lib/utils/artDisplay";
import { season as fixtureSeason, mediaItem } from "../../helpers/fixtures";

const movie = mediaItem({
  id: 1,
  title: "Alien",
  media_type: "movie",
  folder_path: "/movies/Alien",
  poster_hash: "old-hash",
  background_hash: "bg-hash",
  server_item_id: "plex-1",
  poster_url: "https://image.test/poster.jpg",
  background_url: "https://image.test/bg.jpg",
});

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
    const itemWithoutLocal = {
      ...movie,
      poster_hash: null,
      background_hash: null,
    };
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
    const unmanagedItem = {
      ...movie,
      poster_hash: null,
      background_hash: null,
      server_item_id: null,
    };
    expect(itemArtDisplayUrl(unmanagedItem, "poster")).toBeNull();
    expect(itemArtDisplayUrl(unmanagedItem, "background")).toBeNull();
  });

  it("shows the chosen links of an item without a folder", () => {
    const chosen = {
      ...movie,
      folder_path: null,
      poster_hash: null,
      background_hash: null,
      server_item_id: null,
      poster_preview_url: "https://image.test/poster-small.jpg",
    };
    // Shown by its preview everywhere, as a search result shows it; opened in full.
    expect(itemArtDisplayUrl(chosen, "poster")).toBe("https://image.test/poster-small.jpg");
    expect(itemPosterOriginalUrl(chosen)).toBe("https://image.test/poster.jpg");
    expect(itemArtDisplayUrl({ ...chosen, poster_preview_url: null }, "poster")).toBe(
      "https://image.test/poster.jpg",
    );
    expect(itemArtDisplayUrl(chosen, "background")).toBe("https://image.test/bg.jpg");
    expect(
      seasonPosterUrls(
        chosen,
        fixtureSeason({ poster_url: "https://image.test/s.jpg", poster_preview_url: null }),
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
      poster_hash: "season-hash",
      server_item_id: "plex-season-1",
      poster_url: "https://image.test/season.jpg",
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
      poster_hash: null,
      server_item_id: "plex-season-2",
      poster_url: "https://image.test/season.jpg",
    });
    const providerUrls = seasonPosterUrls(show, providerSeason);
    expect(providerUrls.src).toContain("/api/library/seasons/21/provider-art");
    expect(providerUrls.fallbackSrc).toBeNull();

    // 3. Null when neither exists (never remote URL)
    const unmanagedSeason = fixtureSeason({
      id: 22,
      media_item_id: show.id,
      season_num: 3,
      poster_hash: null,
      server_item_id: null,
      poster_url: "https://image.test/season.jpg",
    });
    const unmanagedUrls = seasonPosterUrls(show, unmanagedSeason);
    expect(unmanagedUrls.src).toBeNull();
    expect(unmanagedUrls.fallbackSrc).toBeNull();
    expect(seasonPosterUrls(null, localSeason)).toEqual({ src: null, fallbackSrc: null });
  });

  it("sizes collection images, which only exist on the media server", () => {
    expect(collectionImageUrl("/api/collections/7/image/poster?t=v1")).toBe(
      "/api/collections/7/image/poster?t=v1&size=display",
    );
    expect(collectionImageUrl(null)).toBeNull();
  });
});
