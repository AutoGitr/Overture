import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getItemOptions,
  getCatalogEntryOptions,
  getSeasonsOptions,
  getTmdbItemOptions,
  listCollectionsOptions,
  listItemsOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import { client } from "../../../generated/rest/client.gen";
import type {
  CollectionRead,
  MediaItemListResponse,
  MediaItemRead,
} from "../../../generated/rest/types.gen";
import {
  applyBulkItemOperation,
  bulkSetCollectionMonitoredInCache,
  findCachedLibraryItem,
  invalidateSeasons,
  patchCollection,
  storeCatalogDetail,
  refreshItem,
  removeLibraryItem,
  upsertLibraryItem,
} from "../../../lib/rest/cache";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToItem, navigate, route } from "../../../lib/router/routes";
import { mockFetch } from "../../helpers/fetch";
import {
  collection as fixtureCollection,
  season as fixtureSeason,
  mediaItem,
  catalogDetail,
  catalogEntry,
} from "../../helpers/fixtures";

const movie = mediaItem({
  id: 1,
  title: "Alien",
  media_type: "movie",
});

const show = mediaItem({
  id: 2,
  title: "Twin Peaks",
  media_type: "show",
});

const movieKey = listItemsOptions({ query: { media_type: "movie" } }).queryKey;
const showKey = listItemsOptions({ query: { media_type: "show" } }).queryKey;

function seedLibrary(movies: MediaItemRead[] = [], shows: MediaItemRead[] = []) {
  queryClient.setQueryData(movieKey, {
    items: movies,
    total: movies.length,
  });
  queryClient.setQueryData(showKey, {
    items: shows,
    total: shows.length,
  });
}

describe("REST cache helpers", () => {
  beforeEach(async () => {
    queryClient.clear();
    client.setConfig({ baseUrl: location.origin });
    await navigate("/movies", { replace: true });
  });

  /** Open *item* as the detail view, the way a click in the sidebar does. */
  async function openItem(item: MediaItemRead) {
    await goToItem(item);
    expect(route.params.itemSlug).toMatch(new RegExp(`^${item.id}-`));
  }

  it.each(["artwork", "themes"] as const)(
    "refetches lists, details and seasons after clearing %s, whose status the server computes",
    (operation) => {
      const item = { ...show, poster_url: "poster", art_status: "complete" as const };
      seedLibrary([movie], [item]);
      const detailKey = getItemOptions({ path: { item_id: item.id } }).queryKey;
      const seasonsKey = getSeasonsOptions({ path: { item_id: item.id } }).queryKey;
      queryClient.setQueryData(detailKey, item);
      queryClient.setQueryData(seasonsKey, [fixtureSeason({ poster_url: "season" })]);
      mockFetch({ items: [], total: 0 });

      applyBulkItemOperation({ item_ids: [item.id], operation });

      for (const key of [showKey, detailKey, seasonsKey]) {
        expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
      }
      // Nothing is patched locally with a guessed status.
      expect(findCachedLibraryItem(item.id)).toEqual(item);
    },
  );

  it("applies bulk deletion idempotently and leaves the deleted open item", async () => {
    seedLibrary([movie], [show]);
    await openItem(show);
    const detailKey = getItemOptions({ path: { item_id: show.id } }).queryKey;
    const seasonsKey = getSeasonsOptions({ path: { item_id: show.id } }).queryKey;
    queryClient.setQueryData(detailKey, show);
    queryClient.setQueryData(seasonsKey, [fixtureSeason()]);

    // The same committed result arrives through REST and the live connection.
    applyBulkItemOperation({ item_ids: [movie.id, show.id], operation: "delete" });
    applyBulkItemOperation({ item_ids: [movie.id, show.id], operation: "delete" });

    expect(queryClient.getQueryData(movieKey)).toEqual({ items: [], total: 0 });
    expect(queryClient.getQueryData(showKey)).toEqual({ items: [], total: 0 });
    expect(queryClient.getQueryData(detailKey)).toBeUndefined();
    expect(queryClient.getQueryData(seasonsKey)).toBeUndefined();
    await vi.waitFor(() => expect(route.pathname).toBe("/shows"));
  });

  it("applies bulk monitoring to lists and the details the open item follows, without requests", () => {
    seedLibrary([movie], [show]);
    const detailKey = getItemOptions({ path: { item_id: show.id } }).queryKey;
    queryClient.setQueryData(detailKey, show);
    const { calls } = mockFetch({});

    applyBulkItemOperation({ item_ids: [show.id], operation: "unmonitor" });

    expect(findCachedLibraryItem(show.id)?.monitored).toBe(false);
    expect(queryClient.getQueryData(detailKey)).toMatchObject({ monitored: false });
    expect(findCachedLibraryItem(movie.id)).toEqual(movie);
    expect(calls).toHaveLength(0);
  });

  it("upserts items and keeps list totals stable for existing entries", () => {
    seedLibrary([movie], []);

    upsertLibraryItem({ ...movie, title: "Alien: Director Cut" });
    upsertLibraryItem(show);

    expect(queryClient.getQueryData<MediaItemListResponse>(movieKey)).toMatchObject({
      items: [{ id: 1, title: "Alien: Director Cut" }],
      total: 1,
    });
    expect(queryClient.getQueryData<MediaItemListResponse>(showKey)).toMatchObject({
      items: [{ id: 2 }],
      total: 1,
    });
    expect(findCachedLibraryItem(2)).toEqual(show);
  });

  it("preserves item order in-place when updating existing entries", () => {
    const movie2 = mediaItem({ id: 2, title: "Blade Runner", media_type: "movie" });
    const movie3 = mediaItem({ id: 3, title: "Gladiator", media_type: "movie" });
    seedLibrary([movie, movie2, movie3], []);

    // Update the middle item
    upsertLibraryItem({ ...movie2, title: "Blade Runner 2049" });

    const updated = queryClient.getQueryData<MediaItemListResponse>(movieKey);
    expect(updated?.items.map((item) => item.id)).toEqual([1, 2, 3]);
    expect(updated?.items[1]?.title).toBe("Blade Runner 2049");
  });

  it("moves items between media-type lists", () => {
    seedLibrary([movie], []);

    upsertLibraryItem({ ...movie, media_type: "show" });

    expect(queryClient.getQueryData<MediaItemListResponse>(movieKey)).toMatchObject({
      items: [],
      total: 0,
    });
    expect(queryClient.getQueryData<MediaItemListResponse>(showKey)).toMatchObject({
      items: [{ id: 1, media_type: "show" }],
      total: 1,
    });
  });

  it("removes items and leaves the removed open item", async () => {
    seedLibrary([movie], [show]);
    await openItem(movie);

    removeLibraryItem(movie.id);

    expect(queryClient.getQueryData<MediaItemListResponse>(movieKey)).toMatchObject({
      items: [],
      total: 0,
    });
    expect(queryClient.getQueryData<MediaItemListResponse>(showKey)).toMatchObject({
      items: [{ id: 2 }],
      total: 1,
    });
    await vi.waitFor(() => expect(route.pathname).toBe("/movies"));
  });

  it("treats an item the server removed as gone", async () => {
    seedLibrary([movie], [show]);
    await openItem(movie);

    upsertLibraryItem({ ...movie, server_removed_at: "2026-01-01T00:00:00Z" });

    expect(findCachedLibraryItem(movie.id)).toBeUndefined();
    await vi.waitFor(() => expect(route.pathname).toBe("/movies"));
  });

  it("refreshes an item through Query and patches its list entry", async () => {
    seedLibrary([movie], []);
    queryClient.setQueryData(getItemOptions({ path: { item_id: movie.id } }).queryKey, movie);
    const { fetchMock } = mockFetch({ ...movie, title: "Alien Redux" });

    await refreshItem(movie.id);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(
      queryClient.getQueryData(getItemOptions({ path: { item_id: movie.id } }).queryKey),
    ).toMatchObject({
      title: "Alien Redux",
    });
    expect(findCachedLibraryItem(movie.id)?.title).toBe("Alien Redux");
  });

  it("marks an item's seasons stale without touching other items", async () => {
    const season = fixtureSeason({
      id: 20,
      media_item_id: show.id,
      season_num: 1,
      title: "Season 1",
    });
    const seasonsKey = getSeasonsOptions({ path: { item_id: show.id } }).queryKey;
    const otherKey = getSeasonsOptions({ path: { item_id: movie.id } }).queryKey;
    queryClient.setQueryData(seasonsKey, [season]);
    queryClient.setQueryData(otherKey, []);

    await invalidateSeasons(show.id);

    expect(queryClient.getQueryState(seasonsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(otherKey)?.isInvalidated).toBe(false);
  });

  it("sets the monitoring of several collections in every list", () => {
    const key = listCollectionsOptions({ query: { media_type: "movie" } }).queryKey;
    queryClient.setQueryData(key, [
      fixtureCollection({ id: 1, monitored: false }),
      fixtureCollection({ id: 2, monitored: false }),
      fixtureCollection({ id: 3, monitored: false }),
    ]);

    bulkSetCollectionMonitoredInCache([1, 3], true);

    expect(
      queryClient.getQueryData<CollectionRead[]>(key)?.map((collection) => collection.monitored),
    ).toEqual([true, false, true]);
  });

  it("patches collection lists", () => {
    const collection = fixtureCollection({
      id: 1,
      title: "Action",
      media_type: "movie",
      monitored: false,
      has_theme: false,
      server_type: "plex",
    });
    const key = listCollectionsOptions({ query: { media_type: "movie" } }).queryKey;
    queryClient.setQueryData(key, [collection]);

    patchCollection(collection.id, { has_theme: true, youtube_id: "abc123" });
    patchCollection(collection.id, { monitored: true });

    expect(queryClient.getQueryData<CollectionRead[]>(key)).toMatchObject([
      { monitored: true, has_theme: true, youtube_id: "abc123" },
    ]);
  });
});

describe("TMDB matches", () => {
  const tmdbKey = getTmdbItemOptions({ path: { media_type: "movie", tmdb_id: 603 } }).queryKey;
  const libraryKey = listItemsOptions({ query: { media_type: "movie" } }).queryKey;

  beforeEach(() => {
    queryClient.clear();
    queryClient.setQueryData<MediaItemListResponse>(libraryKey, { items: [movie], total: 1 });
    queryClient.setQueryData(tmdbKey, {
      media_type: "movie",
      tmdb_id: 603,
      title: "The Matrix",
      year: 1999,
      tvdb_id: null,
      imdb_id: null,
      poster_url: null,
      poster_preview_url: null,
      background_url: null,
      existing_item_id: null,
      seasons: [],
    });
  });

  it("go stale when an item is stored", () => {
    upsertLibraryItem(mediaItem({ ...movie, title: "Alien (edited)" }));
    expect(queryClient.getQueryState(tmdbKey)?.isInvalidated).toBe(false);

    upsertLibraryItem(mediaItem({ id: 7, media_type: "movie", tmdb_id: 603 }));
    expect(queryClient.getQueryState(tmdbKey)?.isInvalidated).toBe(true);
  });

  it("go stale when an item is removed", () => {
    removeLibraryItem(999);
    expect(queryClient.getQueryState(tmdbKey)?.isInvalidated).toBe(false);

    removeLibraryItem(movie.id);
    expect(queryClient.getQueryState(tmdbKey)?.isInvalidated).toBe(true);
  });
});

describe("catalog draft cache", () => {
  it("updates every identity alias for the same entry while keeping other media types separate", () => {
    queryClient.clear();
    const oldKey = getCatalogEntryOptions({
      path: { media_type: "show", entry_key: "tvdb-81189" },
    }).queryKey;
    const target = { media_type: "show", entry_key: "tmdb-12" } as const;
    const detail = catalogDetail({
      entry_key: "tmdb-12",
      entry: catalogEntry({ media_type: "show", tmdb_id: 12, tvdb_id: 81189, seasons: [] }),
    });
    queryClient.setQueryData(oldKey, detail);
    const movieKey = getCatalogEntryOptions({
      path: { media_type: "movie", entry_key: "tmdb-12" },
    }).queryKey;
    const movie = catalogDetail({ entry_key: "tmdb-12", entry: catalogEntry({ tmdb_id: 12 }) });
    queryClient.setQueryData(movieKey, movie);
    const updated = {
      ...detail,
      draft: { ...detail.entry, poster_url: "https://image.test/new.jpg" },
    };
    storeCatalogDetail(target, updated);
    expect(queryClient.getQueryData(oldKey)).toEqual(updated);
    expect(queryClient.getQueryData(getCatalogEntryOptions({ path: target }).queryKey)).toEqual(
      updated,
    );
    expect(queryClient.getQueryData(movieKey)).toEqual(movie);
  });
});
