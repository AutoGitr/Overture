import { beforeEach, describe, expect, it } from "vitest";
import { getSeasonsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { client } from "../../../generated/rest/client.gen";
import SeasonGrid from "../../../lib/components/SeasonGrid.svelte";
import { invalidateSeasons } from "../../../lib/rest/cache";
import { queryClient } from "../../../lib/rest/queryClient";
import { mockFetchSequence } from "../../helpers/fetch";
import { season as fixtureSeason, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const show = mediaItem({ id: 7, title: "Twin Peaks", media_type: "show" });
const movie = mediaItem({ id: 8, title: "Alien", media_type: "movie" });

function seasons(title: string) {
  return [fixtureSeason({ id: 70, media_item_id: 7, season_num: 1, title, file_count: 3 })];
}

describe("SeasonGrid query lifecycle", () => {
  beforeEach(() => {
    queryClient.clear();
    client.setConfig({ baseUrl: location.origin });
  });

  it("renders seasons for the selected show", async () => {
    mockFetchSequence([{ body: seasons("Season 1") }]);

    const view = renderWithQueryClient(SeasonGrid, { item: show, preview: null });

    expect(await view.findByText("Season 1")).toBeInTheDocument();
  });

  it("refreshes rendered seasons after invalidation", async () => {
    mockFetchSequence([{ body: seasons("Season 1") }, { body: seasons("Season One") }]);

    const view = renderWithQueryClient(SeasonGrid, { item: show, preview: null });
    await view.findByText("Season 1");

    await invalidateSeasons(show.id);

    expect(await view.findByText("Season One")).toBeInTheDocument();
  });

  it("shows a TMDB title's seasons without asking the server", async () => {
    const { calls } = mockFetchSequence([]);
    const preview = {
      media_type: "show" as const,
      tmdb_id: 1399,
      title: "Show",
      year: null,
      tvdb_id: null,
      imdb_id: null,
      poster_url: null,
      poster_preview_url: null,
      background_url: null,
      existing_item_id: null,
      seasons: [
        {
          season_num: 0,
          title: "Specials",
          poster_url: null,
          poster_preview_url: "https://image.tmdb.org/t/p/w342/specials.jpg",
        },
      ],
    };

    const view = renderWithQueryClient(SeasonGrid, { item: null, preview });

    expect(await view.findByText("Specials")).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("asks for nothing when the selection is a movie", () => {
    const { calls } = mockFetchSequence([]);

    renderWithQueryClient(SeasonGrid, { item: movie, preview: null });

    expect(calls).toEqual([]);
    expect(
      queryClient.getQueryData(getSeasonsOptions({ path: { item_id: movie.id } }).queryKey),
    ).toBeUndefined();
  });
});
