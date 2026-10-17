import { screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getItemOptions,
  getTmdbArtSourcesOptions,
  getTmdbItemOptions,
} from "../../../../generated/rest/@tanstack/svelte-query.gen";
import { client } from "../../../../generated/rest/client.gen";
import { upsertLibraryItem } from "../../../../lib/rest/cache";
import { queryClient } from "../../../../lib/rest/queryClient";
import ItemPage from "../../../../lib/router/pages/ItemPage.svelte";
import { navigate, route } from "../../../../lib/router/routes";
import { publicDatasetState } from "../../../../lib/stores/publicDatasetState.svelte";
import { selectedState } from "../../../../lib/stores/selectedState.svelte";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { mediaItem } from "../../../helpers/fixtures";
import { renderWithQueryClient } from "../../../helpers/render";

describe("TMDB item routes", () => {
  beforeEach(async () => {
    queryClient.clear();
    publicDatasetState.reset();
    selectedState.selectItem(null);
    settingsState.load({ workflow: "art", auto_match_art: false });
    for (const media_type of ["movie", "show"] as const) {
      queryClient.setQueryData(
        getTmdbItemOptions({ path: { media_type, tmdb_id: 603 } }).queryKey,
        {
          media_type,
          tmdb_id: 603,
          title: media_type === "movie" ? "A movie" : "A different show",
          year: 1999,
          tvdb_id: null,
          imdb_id: null,
          poster_url: null,
          poster_preview_url: null,
          background_url: null,
          existing_item_id: null,
          seasons: [],
        },
      );
      queryClient.setQueryData(
        getTmdbArtSourcesOptions({
          path: { media_type, tmdb_id: 603, art_type: "poster" },
          query: { season_num: null },
        }).queryKey,
        { sources: {}, current_url: null },
      );
    }
    await navigate("/movies/:itemSlug", { params: { itemSlug: "tmdb-603-a-movie" } });
  });

  it("replaces a movie preview when a show has the same TMDB ID", async () => {
    renderWithQueryClient(ItemPage);
    expect(await screen.findByRole("heading", { name: "A movie" })).toBeInTheDocument();

    await navigate("/shows/:itemSlug", { params: { itemSlug: "tmdb-603-a-different-show" } });

    expect(await screen.findByRole("heading", { name: "A different show" })).toBeInTheDocument();
    await waitFor(() => expect(selectedState.preview?.media_type).toBe("show"));
    expect(screen.queryByRole("heading", { name: "A movie" })).not.toBeInTheDocument();
  });
});

describe("stored TMDB titles", () => {
  beforeEach(() => {
    queryClient.clear();
    client.setConfig({ baseUrl: location.origin });
    publicDatasetState.reset();
    selectedState.selectItem(null);
    settingsState.load({ workflow: "art", auto_match_art: false });
  });

  it("re-checks a stale cached title instead of opening it as new", async () => {
    const key = getTmdbItemOptions({ path: { media_type: "movie", tmdb_id: 604 } }).queryKey;
    const title = {
      media_type: "movie" as const,
      tmdb_id: 604,
      title: "The Matrix Reloaded",
      year: 2003,
      tvdb_id: null,
      imdb_id: null,
      poster_url: null,
      poster_preview_url: null,
      background_url: null,
      seasons: [],
    };
    // Cached while new; the title has been stored since.
    queryClient.setQueryData(key, { ...title, existing_item_id: null });
    await queryClient.invalidateQueries({ queryKey: key, refetchType: "none" });
    const stored = mediaItem({ id: 7, title: "The Matrix Reloaded", tmdb_id: 604 });
    queryClient.setQueryData(getItemOptions({ path: { item_id: 7 } }).queryKey, stored);
    let answer!: () => void;
    const answered = new Promise<void>((resolve) => (answer = resolve));
    const recheck = vi.fn(async () => {
      await answered;
      return Response.json({ ...title, existing_item_id: 7 });
    });
    vi.stubGlobal("fetch", recheck);
    await navigate("/movies/:itemSlug", { params: { itemSlug: "tmdb-604-the-matrix-reloaded" } });

    renderWithQueryClient(ItemPage);
    // While the re-check runs, the cached answer does not open the title as new.
    await waitFor(() => expect(recheck).toHaveBeenCalled());
    expect(selectedState.preview).toBeNull();
    expect(screen.queryByRole("heading", { name: "The Matrix Reloaded" })).toBeNull();

    answer();
    await waitFor(() => expect(route.pathname).toMatch(/^\/movies\/7-the-matrix-reloaded/));
    expect(selectedState.preview).toBeNull();
  });
});

describe("stored item routes", () => {
  beforeEach(() => {
    queryClient.clear();
    publicDatasetState.reset();
    selectedState.selectItem(null);
    settingsState.load({ workflow: "art", auto_match_art: false });
  });

  it("keeps the open item in step with its cached record", async () => {
    const item = mediaItem({ id: 7, title: "Alien", monitored: true });
    queryClient.setQueryData(getItemOptions({ path: { item_id: 7 } }).queryKey, item);
    vi.stubGlobal("fetch", () => Promise.resolve(Response.json({}, { status: 404 })));
    await navigate("/movies/:itemSlug", { params: { itemSlug: "7-alien" } });

    renderWithQueryClient(ItemPage);
    await waitFor(() => expect(selectedState.item?.id).toBe(7));

    upsertLibraryItem({ ...item, monitored: false });
    await waitFor(() => expect(selectedState.item?.monitored).toBe(false));
  });
});
