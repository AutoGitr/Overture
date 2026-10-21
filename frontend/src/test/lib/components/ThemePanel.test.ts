import { appSettings } from "../../helpers/fixtures";
import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { storePublicDatasetStatus } from "../../../lib/realtime/cache";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ThemePanel from "../../../lib/components/ThemePanel.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import type { MediaItemRead, TmdbItemPreview } from "../../../generated/rest/types.gen";
import { publicDatasetStatus, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

type Shown = { item: MediaItemRead | null; preview: TmdbItemPreview | null };
let shown: Shown = { item: null, preview: null };

function showItem(item: MediaItemRead) {
  shown = { item, preview: null };
  routed.itemId = item.id;
}

function showPreview(preview: TmdbItemPreview) {
  shown = { item: null, preview };
  routed.itemId = null;
}

function renderPanel() {
  return renderWithQueryClient(ThemePanel, shown);
}

const {
  selectTheme,
  getPublicDatasetSources,
  getTmdbPublicDatasetSources,
  openPersistedItem,
  upsertLibraryItem,
  searchYoutube,
  selectTmdbTheme,
  trackQueuedItemJob,
  routed,
} = vi.hoisted(() => ({
  selectTheme: vi.fn(),
  getPublicDatasetSources: vi.fn(),
  getTmdbPublicDatasetSources: vi.fn(),
  openPersistedItem: vi.fn(),
  upsertLibraryItem: vi.fn(),
  searchYoutube: vi.fn(),
  selectTmdbTheme: vi.fn(),
  trackQueuedItemJob: vi.fn(),
  routed: { itemId: null as number | null },
}));
vi.mock("../../../generated/rest/sdk.gen", () => ({
  selectTheme,
  getPublicDatasetSources,
  getTmdbPublicDatasetSources,
  searchYoutube,
  selectTmdbTheme,
}));
vi.mock("../../../lib/utils/tmdbItems", () => ({ openPersistedItem }));
vi.mock("../../../lib/rest/cache", () => ({ upsertLibraryItem }));
vi.mock("../../../lib/router/routes", () => ({
  goToItemArt: vi.fn(),
  goToItemThemes: vi.fn(),
  goToSeason: vi.fn(),
  route: { pathname: "/movies/1-alien/themes" },
  routedItemId: () => routed.itemId,
}));
vi.mock("../../../lib/stores/downloadState.svelte", () => ({
  downloadState: {
    getJobsForItem: () => [],
    trackQueuedItemJob,
  },
}));

describe("ThemePanel search", () => {
  beforeEach(() => {
    queryClient.clear();
    settingsState.load(appSettings({ workflow: "themes" }));
    showItem(mediaItem({ title: "Alien" }));
    vi.resetAllMocks();
    searchYoutube.mockResolvedValue({ data: { results: [] } });
    selectTheme.mockResolvedValue({
      data: { selection: { job_id: "theme-job", status: "enqueued" }, item: mediaItem({ id: 1 }) },
    });
  });

  it("shows an empty result only after a successful search", async () => {
    renderPanel();
    expect(await screen.findByRole("status")).toHaveTextContent("No themes found");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains recovered provenance and clears the label when switching items", async () => {
    showItem(
      mediaItem({
        youtube_id: "UuPb1J_RCJM",
        youtube_id_source: "source_url",
      }),
    );
    const view = renderPanel();
    expect(screen.getByText("Recovered from an embedded YouTube source URL")).toBeInTheDocument();
    await view.rerender({ item: mediaItem({ id: 2, youtube_id: "hXVsOWrU6Ws" }), preview: null });
    await waitFor(() => {
      expect(screen.queryByText(/Recovered from/)).not.toBeInTheDocument();
    });
  });

  it("treats a missing OvertureDB entry as a normal empty result", async () => {
    storePublicDatasetStatus(publicDatasetStatus());
    getPublicDatasetSources.mockResolvedValue({
      data: { found: false, item: null, seasons: [] },
    });

    renderPanel();

    await waitFor(() => expect(getPublicDatasetSources).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/OvertureDB theme:/)).not.toBeInTheDocument();
  });

  it("announces a search failure and clears it when the next search succeeds", async () => {
    searchYoutube.mockRejectedValueOnce(new ApiError("Bad search", 400, "search-request"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("search-request");
    expect(screen.queryByText(/No themes found/)).not.toBeInTheDocument();
    await fireEvent.input(screen.getByLabelText("Search themes"), {
      target: { value: "Alien soundtrack" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(searchYoutube).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("status")).toHaveTextContent("No themes found");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    { primary: null, secondary: "secondary12", current: null, choices: ["secondary12"] },
    {
      primary: "primary_123",
      secondary: "secondary12",
      current: null,
      choices: ["primary_123", "secondary12"],
    },
    { primary: "primary_123", secondary: "primary_123", current: null, choices: ["primary_123"] },
    {
      primary: "primary_123",
      secondary: "secondary12",
      current: "secondary12",
      choices: ["primary_123"],
    },
    {
      primary: "primary_123",
      secondary: "secondary12",
      current: "primary_123",
      choices: ["secondary12"],
    },
  ])(
    "offers distinct, unselected dataset themes in the unified grid: $primary / $secondary / $current",
    async ({ primary, secondary, current, choices }) => {
      storePublicDatasetStatus(publicDatasetStatus());
      showItem(mediaItem({ id: 7, youtube_id: current }));
      getPublicDatasetSources.mockResolvedValue({
        data: {
          found: true,
          item: { youtube_id_overturedb: primary, youtube_id_themerrdb: secondary },
          seasons: [],
        },
      });
      renderPanel();

      const buttons = await screen.findAllByRole("button", { name: "Select" });
      expect(buttons).toHaveLength(choices.length);
      for (const id of choices) {
        expect(document.querySelector(`iframe[src*="${id}"]`)).toBeInTheDocument();
      }
      await fireEvent.click(buttons[choices.length - 1]!);
      await waitFor(() =>
        expect(selectTheme).toHaveBeenCalledWith(
          expect.objectContaining({
            path: { item_id: 7 },
            body: { youtube_id: choices[choices.length - 1] },
          }),
        ),
      );

      storePublicDatasetStatus(publicDatasetStatus({ enabled: false }));
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Select" })).not.toBeInTheDocument(),
      );
    },
  );

  it("loads currently selected video first, then OvertureDB, then ThemerrDB, then YouTube search with correct badges and deduplication", async () => {
    storePublicDatasetStatus(publicDatasetStatus());
    showItem(
      mediaItem({
        id: 7,
        title: "Alien",
        youtube_id: "selected_yt",
        youtube_title: "Alien Current Theme",
      }),
    );
    getPublicDatasetSources.mockResolvedValue({
      data: {
        found: true,
        item: {
          youtube_id_overturedb: "overture_yt",
          youtube_id_themerrdb: "themerr_yt",
        },
        seasons: [],
      },
    });
    searchYoutube.mockResolvedValue({
      data: {
        results: [
          {
            id: "overture_yt",
            title: "Alien Overture Suite",
            channel: "OST Channel",
            duration: 200,
            thumbnail: null,
            url: "https://youtu.be/overture_yt",
          },
          {
            id: "search_yt",
            title: "Alien Search Result",
            channel: "Search Channel",
            duration: 180,
            thumbnail: null,
            url: "https://youtu.be/search_yt",
          },
        ],
      },
    });

    renderPanel();

    // Wait for dataset sources and search results to settle into the grid
    await waitFor(() => {
      const iframes = screen.getAllByTitle(/.+/);
      expect(iframes).toHaveLength(4);
    });

    // Check all iframes in order
    const iframes = screen.getAllByTitle(/.+/);
    const iframeSrcs = iframes.map((iframe) => iframe.getAttribute("src"));
    expect(iframeSrcs).toEqual([
      "https://www.youtube-nocookie.com/embed/selected_yt",
      "https://www.youtube-nocookie.com/embed/overture_yt",
      "https://www.youtube-nocookie.com/embed/themerr_yt",
      "https://www.youtube-nocookie.com/embed/search_yt",
    ]);

    // Check badges
    expect(screen.getByText("Currently Selected")).toHaveClass("badge", "badge-success");
    expect(screen.getByText("OvertureDB")).toHaveClass("badge", "badge-accent");
    expect(screen.getByText("ThemerrDB")).toHaveClass("badge", "badge-warning");

    // Check overwrite button on current theme and select buttons on others
    expect(screen.getByRole("button", { name: "Overwrite" })).toBeInTheDocument();
    const selectButtons = screen.getAllByRole("button", { name: "Select" });
    expect(selectButtons).toHaveLength(3); // overture_yt, themerr_yt, search_yt

    // Verify old public-theme container is removed
    expect(document.querySelector(".public-theme")).not.toBeInTheDocument();
  });

  it("enriches ThemerrDB and OvertureDB selections with YouTube title, channel, and duration", async () => {
    storePublicDatasetStatus(publicDatasetStatus());
    showItem(
      mediaItem({
        id: 7,
        title: "Alien",
      }),
    );
    getPublicDatasetSources.mockResolvedValue({
      data: {
        found: true,
        item: {
          youtube_id_overturedb: "overture_yt",
          youtube_id_themerrdb: "themerr_yt",
        },
        seasons: [],
      },
    });
    searchYoutube.mockResolvedValue({
      data: {
        results: [
          {
            id: "themerr_yt",
            title: "Alien OST - Main Title",
            channel: "Soundtrack Collector",
            duration: 145,
            thumbnail: null,
            url: "https://youtu.be/themerr_yt",
          },
        ],
      },
    });

    renderPanel();

    expect(await screen.findByText("Alien OST - Main Title")).toBeInTheDocument();
    expect(screen.getByText("Soundtrack Collector")).toBeInTheDocument();
    expect(screen.getByText("2:25")).toBeInTheDocument();
  });

  it("keeps search results available when a download fails and permits retry", async () => {
    searchYoutube.mockResolvedValue({
      data: {
        results: [
          {
            channel: "Studio",
            duration: 120,
            id: "video-1",
            thumbnail: null,
            title: "Alien Theme",
            url: "https://youtu.be/video-1",
          },
        ],
      },
    });
    selectTheme
      .mockRejectedValueOnce(new ApiError("Download unavailable", 503, "download-request"))
      .mockResolvedValueOnce({
        data: {
          selection: { job_id: "theme-job", status: "enqueued" },
          item: mediaItem({ id: 1 }),
        },
      });
    renderPanel();

    const select = await screen.findByRole("button", { name: "Select" });
    await fireEvent.click(select);
    expect(await screen.findByRole("alert")).toHaveTextContent("download-request");
    expect(screen.getByText("Alien Theme")).toBeVisible();
    expect(select).toBeEnabled();

    await fireEvent.click(select);
    await waitFor(() => {
      expect(selectTheme).toHaveBeenCalledTimes(2);
      expect(trackQueuedItemJob).toHaveBeenCalledWith({
        jobId: "theme-job",
        mediaItemId: 1,
        jobType: "theme",
      });
      expect(upsertLibraryItem).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not render theme-status block even when item has theme attributes or local theme file", () => {
    showItem(
      mediaItem({
        id: 7,
        youtube_id: "existing",
        theme_file_hash: "theme-hash",
        theme_status: "complete",
      }),
    );
    renderPanel();

    expect(document.querySelector(".theme-status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Theme file exists/)).not.toBeInTheDocument();
  });

  it("switches search button label to Select when input is a YouTube URL and selects directly on click", async () => {
    renderPanel();

    // Wait for the initial automatic search to settle
    expect(await screen.findByRole("button", { name: "Search" })).toBeInTheDocument();
    const input = screen.getByLabelText("Search themes");

    await fireEvent.input(input, {
      target: { value: "https://www.youtube.com/watch?v=abc12345678" },
    });
    expect(screen.getByRole("button", { name: "Select" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();

    await fireEvent.input(input, {
      target: { value: "Alien original soundtrack" },
    });
    expect(screen.getByRole("button", { name: "Search" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select" })).not.toBeInTheDocument();

    await fireEvent.input(input, {
      target: { value: "https://youtu.be/abc12345678" },
    });
    const selectBtn = screen.getByRole("button", { name: "Select" });
    expect(selectBtn).toBeInTheDocument();

    searchYoutube.mockClear();
    await fireEvent.click(selectBtn);

    await waitFor(() => {
      expect(selectTheme).toHaveBeenCalledWith(
        expect.objectContaining({ path: { item_id: 1 }, body: { youtube_id: "abc12345678" } }),
      );
    });
    expect(searchYoutube).not.toHaveBeenCalled();
  });

  it("fetches dataset themes apart from the search, which runs only once", async () => {
    storePublicDatasetStatus(publicDatasetStatus());
    getPublicDatasetSources.mockResolvedValue({
      data: {
        found: true,
        item: { youtube_id_overturedb: "overture_yt", youtube_id_themerrdb: null },
        seasons: [],
      },
    });
    renderPanel();

    await waitFor(() =>
      expect(searchYoutube).toHaveBeenCalledWith(
        expect.objectContaining({ query: { limit: 10, video_ids: ["overture_yt"] } }),
      ),
    );
    const textSearches = searchYoutube.mock.calls.filter(
      (call) => (call[0] as { query: { query?: string } }).query.query !== undefined,
    );
    expect(textSearches).toHaveLength(1);
  });
});

describe("ThemePanel for TMDB titles", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.resetAllMocks();
    settingsState.load(
      appSettings({ workflow: "themes", theme_search_format: "{title} {year} theme" }),
    );
    storePublicDatasetStatus(publicDatasetStatus());
    showPreview({
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
    getTmdbPublicDatasetSources.mockResolvedValue({
      data: { found: false, item: null, seasons: [] },
    });
    searchYoutube.mockResolvedValue({
      data: { results: [{ id: "abcDEF123_4", title: "Main Theme", duration: 95 }] },
    });
  });

  it("searches by title and stores the title with its first theme", async () => {
    const stored = mediaItem({ id: 9, title: "The Matrix" });
    selectTmdbTheme.mockResolvedValue({
      data: { selection: { job_id: null, status: "selected" }, item: stored },
    });
    renderPanel();

    await waitFor(() =>
      expect(searchYoutube).toHaveBeenCalledWith(
        expect.objectContaining({ query: { query: "The Matrix 1999 theme", limit: 10 } }),
      ),
    );
    expect(getTmdbPublicDatasetSources).toHaveBeenCalledWith(
      expect.objectContaining({ path: { media_type: "movie", tmdb_id: 603 } }),
    );
    expect(getPublicDatasetSources).not.toHaveBeenCalled();

    await screen.findByText("Main Theme");
    await fireEvent.click(screen.getByRole("button", { name: "Select" }));

    await waitFor(() =>
      expect(openPersistedItem).toHaveBeenCalledWith(
        stored,
        { theme: true },
        expect.objectContaining({ itemId: null }),
      ),
    );
    expect(selectTmdbTheme).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { youtube_id: "abcDEF123_4" },
        path: { media_type: "movie", tmdb_id: 603 },
      }),
    );
    expect(selectTheme).not.toHaveBeenCalled();
  });

  it("searches again for a show with the same TMDB ID as the previous movie", async () => {
    const view = renderPanel();
    await screen.findByText("Main Theme");
    await view.rerender({
      item: null,
      preview: { ...shown.preview!, media_type: "show", title: "Different show" },
    });

    await waitFor(() =>
      expect(searchYoutube).toHaveBeenCalledWith(
        expect.objectContaining({ query: { query: "Different show 1999 theme", limit: 10 } }),
      ),
    );
    expect(screen.getByLabelText("Search themes")).toHaveValue("Different show 1999 theme");
  });
});
