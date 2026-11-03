import { appSettings } from "../../helpers/fixtures";
import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { tick } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtPanel from "../../../lib/components/ArtPanel.svelte";
import PasteArtButton from "../../../lib/components/PasteArtButton.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToItemArt, route } from "../../../lib/router/routes";
import { artPreviewState } from "../../../lib/stores/artPreviewState.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import type { MediaItemRead, TmdbItemPreview } from "../../../generated/rest/types.gen";
import { artCandidate, mediaItem, season } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const {
  getArtSources,
  getSeasons,
  getTmdbArtSources,
  matchArt,
  saveArt,
  saveTmdbArt,
  upsertLibraryItem,
  invalidateSeasons,
  trackQueuedItemJob,
  openPersistedItem,
  routed,
} = vi.hoisted(() => ({
  getArtSources: vi.fn(),
  getSeasons: vi.fn(),
  getTmdbArtSources: vi.fn(),
  matchArt: vi.fn(),
  saveArt: vi.fn(),
  saveTmdbArt: vi.fn(),
  upsertLibraryItem: vi.fn(),
  invalidateSeasons: vi.fn(),
  trackQueuedItemJob: vi.fn(),
  openPersistedItem: vi.fn(),
  routed: { itemId: 1 as number | null },
}));

vi.mock("../../../generated/rest/sdk.gen", () => ({
  getArtSources,
  getSeasons,
  getTmdbArtSources,
  matchArt,
  saveArt,
  saveTmdbArt,
}));
vi.mock("../../../lib/utils/tmdbItems", () => ({ openPersistedItem }));
vi.mock("../../../lib/rest/cache", () => ({ upsertLibraryItem, invalidateSeasons }));
vi.mock("../../../lib/router/routes", () => ({
  goToItemArt: vi.fn(),
  goToItemThemes: vi.fn(),
  goToSeason: vi.fn(),
  goToSeasonsList: vi.fn(),
  route: { pathname: "/movies/1-test/art/poster" },
  routedItemId: () => routed.itemId,
}));
vi.mock("../../../lib/stores/downloadState.svelte", () => ({
  downloadState: { trackQueuedItemJob },
}));

function stubClipboard(readText?: () => Promise<string>) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: readText ? { readText } : undefined,
  });
}

/** Ctrl+V outside any input on the art tab. */
async function pasteUrl(url: string) {
  await fireEvent.paste(document.body, { clipboardData: { getData: () => url } });
}

/** Clipboard unreadable (e.g. plain HTTP): the button opens a URL field instead. */
async function enterUrl(url: string) {
  await fireEvent.click(screen.getByRole("button", { name: /Paste URL/ }));
  const input = await screen.findByLabelText("Image URL");
  await fireEvent.input(input, { target: { value: url } });
  await fireEvent.click(screen.getByRole("button", { name: "Save" }));
  return input;
}

type ArtTab = {
  item: MediaItemRead | null;
  preview: TmdbItemPreview | null;
  artType: "poster" | "season_poster";
  drillSeasonNum: number | null;
};

/** The art panel plus the header's paste button, as DetailPanel shows them. */
function renderArtTab(tab: Partial<ArtTab> = {}) {
  const props: ArtTab = {
    item: mediaItem({ id: 1 }),
    preview: null,
    artType: "poster",
    drillSeasonNum: null,
    ...tab,
  };
  const view = renderWithQueryClient(ArtPanel, props);
  renderWithQueryClient(PasteArtButton);
  return { ...view, props };
}

/** The item as the server stores it after a save. */
const saved = mediaItem({ id: 1, title: "Saved" });

function selected(jobId: string | null) {
  return { selection: { job_id: jobId, status: jobId ? "enqueued" : "selected" }, item: saved };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

describe("ArtPanel request ownership", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    queryClient.clear();
    artPreviewState.reset();
    settingsState.load(appSettings({ auto_match_art: false }));
    routed.itemId = 1;
    route.pathname = "/movies/1-test/art/poster";
    getArtSources.mockResolvedValue({ data: { sources: {} } });
    getSeasons.mockResolvedValue({ data: [] });
    saveArt.mockResolvedValue({ data: selected("art-job") });
    stubClipboard();
  });

  it("shows all source candidates with lazy images and highlights local matches", async () => {
    settingsState.load(appSettings({ auto_match_art: true }));
    getArtSources.mockResolvedValue({
      data: {
        sources: {
          tmdb: Array.from({ length: 7 }, (_, n) =>
            artCandidate({ url: `https://image.tmdb.org/t/p/original/${n}.jpg` }),
          ),
        },
      },
    });
    matchArt.mockResolvedValue({
      data: { matches: [artCandidate({ url: "https://image.tmdb.org/t/p/original/matched.jpg" })] },
    });
    const view = renderArtTab();
    await waitFor(() =>
      expect(view.getAllByRole("button", { name: /^Use artwork/ })).toHaveLength(8),
    );
    expect(screen.getByRole("heading", { name: "TMDB" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MATCHED" })).toBeInTheDocument();
    expect(screen.getByText("7")).toHaveClass("badge-muted");
    expect(screen.getByText("1", { selector: "span.badge" })).toHaveClass("badge-success");
    for (const card of view.getAllByRole("button", { name: /^Use artwork/ }))
      expect(card.querySelector("img")).toHaveAttribute("loading", "lazy");
  });

  it("advances only after a successful artwork selection", async () => {
    settingsState.load(
      appSettings({
        auto_match_art: false,
        auto_advance: "slots_and_items",
      }),
    );
    renderArtTab();
    await pasteUrl("https://images.test/poster.jpg");
    await waitFor(() =>
      expect(goToItemArt).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ id: 1 }),
        "background",
      ),
    );
  });

  it("does not redirect after a manual tab change during a save", async () => {
    settingsState.load(
      appSettings({
        auto_match_art: false,
        auto_advance: "slots_and_items",
      }),
    );
    const pending = deferred<{ data: ReturnType<typeof selected> }>();
    saveArt.mockReturnValueOnce(pending.promise);
    renderArtTab();
    await pasteUrl("https://images.test/poster.jpg");
    route.pathname = "/movies/1-test/themes";
    pending.resolve({ data: selected("art-job") });
    await waitFor(() => expect(screen.getByRole("button", { name: /Paste URL/ })).toBeEnabled());
    expect(upsertLibraryItem).toHaveBeenCalledWith(saved);
    expect(goToItemArt).not.toHaveBeenCalled();
  });

  it("matches the selected slot independently of a previous pending match", async () => {
    settingsState.current.auto_match_art = true;
    const first = deferred<{ data: object }>();
    const second = deferred<{ data: object }>();
    matchArt.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { rerender, props } = renderArtTab();
    await waitFor(() => expect(matchArt).toHaveBeenCalledTimes(1));

    await rerender({ ...props, item: mediaItem({ id: 2 }) });
    await waitFor(() => expect(matchArt).toHaveBeenCalledTimes(2));
    expect(matchArt).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ path: { item_id: 2, art_type: "poster" } }),
    );
    second.resolve({ data: { matches: [], total_compared: 1, prefiltered: 0 } });
    expect(await screen.findByText(/No match - nothing within distance/)).toBeInTheDocument();

    first.resolve({
      data: {
        matches: [{ url: "https://images.test/first.jpg", source: "tmdb" }],
        total_compared: 1,
        prefiltered: 0,
      },
    });
    await first.promise;
    await tick();
    expect(screen.queryByText("MATCHED")).not.toBeInTheDocument();
    expect(screen.getByText(/No match - nothing within distance/)).toBeInTheDocument();
  });

  it("keeps a queued download attached to the season that requested it", async () => {
    const pending = deferred<{ data: ReturnType<typeof selected> }>();
    saveArt.mockReturnValue(pending.promise);
    getSeasons.mockResolvedValue({
      data: [
        season({ id: 11, media_item_id: 1, season_num: 1, title: "Season One" }),
        season({ id: 12, media_item_id: 1, season_num: 2, title: "Season Two" }),
      ],
    });
    const { rerender, props } = renderArtTab({
      item: mediaItem({ id: 1, media_type: "show" }),
      artType: "season_poster",
      drillSeasonNum: 1,
    });
    await screen.findByRole("button", { name: "Paste URL & save as season poster" });
    await pasteUrl("https://images.test/one.jpg");
    await waitFor(() => expect(saveArt).toHaveBeenCalledTimes(1));

    await rerender({ ...props, drillSeasonNum: 2 });
    await screen.findByText("Season Two");
    await fireEvent.click(screen.getByRole("button", { name: /Paste URL/ }));
    const input = await screen.findByLabelText("Image URL");
    await fireEvent.input(input, { target: { value: "https://images.test/two.jpg" } });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();

    pending.resolve({ data: selected("download-1") });
    await waitFor(() => {
      expect(trackQueuedItemJob).toHaveBeenCalledWith({
        jobId: "download-1",
        mediaItemId: 1,
        jobType: "art",
        artType: "season_poster",
        seasonId: 11,
      });
      expect(invalidateSeasons).toHaveBeenCalledWith(1);
    });
    expect(screen.getByLabelText("Image URL")).toHaveValue("https://images.test/two.jpg");
  });

  it("preserves a custom URL for retry after a failed save", async () => {
    saveArt.mockRejectedValue(new Error("Cannot queue image"));
    renderArtTab();
    const input = await enterUrl("https://images.test/poster.jpg");

    expect(await screen.findByText("Cannot queue image")).toBeInTheDocument();
    expect(input).toHaveValue("https://images.test/poster.jpg");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("saves the clipboard URL in one click when the clipboard is readable", async () => {
    // The backend canonicalises the link; the panel only trims it.
    stubClipboard(async () => " https://theposterdb.com/poster/207889 ");
    renderArtTab();
    await fireEvent.click(screen.getByRole("button", { name: "Paste URL & save as poster" }));
    await waitFor(() =>
      expect(saveArt).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({ url: "https://theposterdb.com/poster/207889" }),
        }),
      ),
    );
    expect(screen.queryByLabelText("Image URL")).not.toBeInTheDocument();
  });

  it("warns instead of saving when the clipboard holds no image URL", async () => {
    stubClipboard(async () => "Alien (1979)");
    renderArtTab();
    await fireEvent.click(screen.getByRole("button", { name: /Paste URL/ }));
    expect(await screen.findByText("That is not an image URL")).toBeInTheDocument();
    expect(saveArt).not.toHaveBeenCalled();
  });

  it("ignores pastes into other fields", async () => {
    renderArtTab();
    await fireEvent.paste(screen.getByRole("spinbutton"), {
      clipboardData: { getData: () => "https://images.test/poster.jpg" },
    });
    expect(saveArt).not.toHaveBeenCalled();
  });

  it("queues the selected source artwork and refreshes the item", async () => {
    getArtSources.mockResolvedValue({
      data: {
        sources: {
          tmdb: [artCandidate({ preview_url: "https://images.test/preview.jpg" })],
        },
      },
    });
    renderArtTab();

    const candidate = await screen.findByRole("button", { name: /^Use artwork/ });
    await fireEvent.click(candidate);

    await waitFor(() => {
      expect(saveArt).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            height: 1500,
            url: "https://images.test/poster.jpg",
            width: 1000,
          },
          path: { item_id: 1, art_type: "poster" },
          query: { season_id: null },
        }),
      );
      expect(trackQueuedItemJob).toHaveBeenCalledWith({
        jobId: "art-job",
        mediaItemId: 1,
        jobType: "art",
        artType: "poster",
        seasonId: null,
      });
      expect(upsertLibraryItem).toHaveBeenCalledWith(saved);
    });
  });

  it("shows the chosen candidate on the detail page only once the server accepts it", async () => {
    getArtSources.mockResolvedValue({
      data: {
        sources: {
          tmdb: [artCandidate({ preview_url: "https://images.test/preview.jpg" })],
        },
      },
    });
    const accepted = deferred<{ data: ReturnType<typeof selected> }>();
    saveArt.mockReturnValueOnce(accepted.promise);
    const item = mediaItem({ id: 1 });
    renderArtTab({ item });
    const candidate = await screen.findByRole("button", { name: /^Use artwork/ });

    await fireEvent.click(candidate);
    expect(artPreviewState.previewFor(item, "poster")).toBeNull();

    accepted.resolve({ data: selected("art-job") });
    await waitFor(() => {
      expect(artPreviewState.previewFor(item, "poster")).toBe("https://images.test/preview.jpg");
    });
  });

  it("shows no preview for a pasted URL or a rejected choice", async () => {
    saveArt.mockRejectedValueOnce(new Error("Cannot queue image"));
    const item = mediaItem({ id: 1 });
    renderArtTab({ item });
    await enterUrl("https://images.test/rejected.jpg");
    await waitFor(() => expect(saveArt).toHaveBeenCalledTimes(1));
    await enterUrl("https://images.test/pasted.jpg");
    await waitFor(() => expect(upsertLibraryItem).toHaveBeenCalledWith(saved));

    expect(artPreviewState.previewFor(item, "poster")).toBeNull();
  });

  it("renders Distance <= label, clamps threshold input within 0..10, and runs match with clamped threshold", async () => {
    matchArt.mockResolvedValue({ data: { matches: [] } });
    renderArtTab();

    const label = await screen.findByText(/Distance/);
    expect(label).toBeInTheDocument();
    expect(label.textContent).toContain("\u2264");

    const thresholdInput = screen.getByLabelText(/Distance/);
    expect(thresholdInput).toBeInTheDocument();
    expect(thresholdInput).toHaveValue(3);

    await fireEvent.input(thresholdInput, { target: { value: "15" } });
    await fireEvent.change(thresholdInput);
    expect(thresholdInput).toHaveValue(10);

    const matchButton = screen.getByRole("button", { name: "Match poster" });
    expect(matchButton).toBeInTheDocument();
    await fireEvent.click(matchButton);

    await waitFor(() => {
      expect(matchArt).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { item_id: 1, art_type: "poster" },
          query: { season_id: null, threshold: 10 },
        }),
      );
    });
  });
});

describe("ArtPanel for TMDB titles", () => {
  const preview = {
    media_type: "show" as const,
    tmdb_id: 1399,
    title: "Show",
    year: 2011,
    tvdb_id: null,
    imdb_id: null,
    poster_url: null,
    poster_preview_url: null,
    background_url: null,
    existing_item_id: null,
    seasons: [{ season_num: 1, title: "Season 1", poster_url: null, poster_preview_url: null }],
  };

  beforeEach(() => {
    vi.resetAllMocks();
    queryClient.clear();
    settingsState.load(appSettings({ auto_match_art: true }));
    routed.itemId = null;
    route.pathname = "/shows/tmdb-1399-show/art/poster";
    getTmdbArtSources.mockResolvedValue({
      data: { sources: { tmdb: [{ url: "https://images.test/tmdb.jpg", width: 2, height: 3 }] } },
    });
    stubClipboard();
  });

  it("lists sources by TMDB ID and never matches", async () => {
    renderArtTab({ item: null, preview });
    expect(await screen.findByText("TMDB")).toBeInTheDocument();
    expect(getTmdbArtSources).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { media_type: "show", tmdb_id: 1399, art_type: "poster" },
        query: { season_num: null },
      }),
    );
    expect(getArtSources).not.toHaveBeenCalled();
    expect(matchArt).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Match poster/ })).not.toBeInTheDocument();
  });

  it("stores the title with its first season poster and opens the stored item", async () => {
    const stored = mediaItem({ id: 7, media_type: "show" });
    saveTmdbArt.mockResolvedValue({
      data: { selection: { job_id: null, status: "selected" }, item: stored },
    });
    renderArtTab({ item: null, preview, artType: "season_poster", drillSeasonNum: 1 });
    await screen.findByText("Season 1");
    await pasteUrl("https://images.test/one.jpg");

    await waitFor(() =>
      expect(openPersistedItem).toHaveBeenCalledWith(
        stored,
        { artType: "season_poster", seasonNum: 1 },
        expect.objectContaining({ pathname: route.pathname }),
      ),
    );
    expect(saveTmdbArt).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { media_type: "show", tmdb_id: 1399, art_type: "season_poster" },
        query: { season_num: 1 },
      }),
    );
    expect(trackQueuedItemJob).not.toHaveBeenCalled();
  });

  it("resets a slot when a movie and show share a TMDB ID", async () => {
    const { rerender, props } = renderArtTab({ item: null, preview });
    await fireEvent.click(screen.getByRole("button", { name: /Paste URL/ }));
    expect(await screen.findByLabelText("Image URL")).toBeInTheDocument();

    await rerender({
      ...props,
      preview: { ...preview, media_type: "movie", title: "Different movie" },
    });

    await waitFor(() => expect(screen.queryByLabelText("Image URL")).not.toBeInTheDocument());
    expect(getTmdbArtSources).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { media_type: "movie", tmdb_id: 1399, art_type: "poster" },
      }),
    );
  });
});

describe("ArtPanel for items without a folder", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    queryClient.clear();
    artPreviewState.reset();
    settingsState.load(appSettings({ auto_match_art: false }));
    routed.itemId = 1;
    route.pathname = "/movies/1-test/art/poster";
    getArtSources.mockResolvedValue({ data: { sources: {} } });
    stubClipboard();
  });

  it("tracks no download when only the choice was recorded", async () => {
    saveArt.mockResolvedValue({ data: selected(null) });
    renderArtTab();
    await pasteUrl("https://images.test/poster.jpg");

    await waitFor(() => expect(upsertLibraryItem).toHaveBeenCalledWith(saved));
    expect(trackQueuedItemJob).not.toHaveBeenCalled();
  });
});
