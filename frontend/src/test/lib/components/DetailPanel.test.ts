import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { tick } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DetailPanel from "../../../lib/components/DetailPanel.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { navigate, route } from "../../../lib/router/routes";
import { artPreviewState } from "../../../lib/stores/artPreviewState.svelte";
import { publicDatasetState } from "../../../lib/stores/publicDatasetState.svelte";
import { selectedState } from "../../../lib/stores/selectedState.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { mediaItem, season } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const {
  clearAllArt,
  clearArt,
  clearTheme,
  confirmAction,
  deleteItem,
  getSeasons,
  invalidateSeasons,
  refreshItem,
  setMonitored,
  upsertLibraryItem,
} = vi.hoisted(() => ({
  clearAllArt: vi.fn(),
  clearArt: vi.fn(),
  clearTheme: vi.fn(),
  confirmAction: vi.fn(),
  deleteItem: vi.fn(),
  getSeasons: vi.fn(),
  invalidateSeasons: vi.fn(),
  refreshItem: vi.fn(),
  setMonitored: vi.fn(),
  upsertLibraryItem: vi.fn(),
}));

vi.mock("../../../generated/rest/sdk.gen", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../generated/rest/sdk.gen")>()),
  clearAllArt,
  clearArt,
  clearTheme,
  deleteItem,
  getSeasons,
  setMonitored,
}));
vi.mock("../../../lib/rest/cache", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/rest/cache")>()),
  invalidateSeasons,
  refreshItem,
  upsertLibraryItem,
}));
vi.mock("../../../lib/stores/notificationState.svelte", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/stores/notificationState.svelte")>()),
  confirmAction,
}));

const preview = {
  media_type: "movie" as const,
  tmdb_id: 603,
  title: "The Matrix",
  year: 1999,
  tvdb_id: null,
  imdb_id: "tt0133093",
  poster_url: "https://image.tmdb.org/t/p/original/matrix.jpg",
  poster_preview_url: "https://image.tmdb.org/t/p/w342/matrix.jpg",
  background_url: null,
  existing_item_id: null,
  seasons: [],
};

// The title is the heading beside it, so the poster image has no name of its own.
const posterImage = (container: HTMLElement) =>
  container.querySelector<HTMLImageElement>(".detail-poster img");

describe("DetailPanel", () => {
  beforeEach(() => {
    queryClient.clear();
    publicDatasetState.reset();
  });

  it("shows a TMDB title without the controls of a stored record", () => {
    selectedState.selectPreview(preview);
    // A view without a panel keeps the test to the header and tabs.
    selectedState.mode = "monitor";
    const { container } = renderWithQueryClient(DetailPanel);

    expect(screen.getByRole("heading", { name: "The Matrix" })).toBeInTheDocument();
    // The search result's own poster, already loaded by the sidebar.
    expect(posterImage(container)).toHaveAttribute("src", preview.poster_preview_url);
    // No alt text for a browser to draw in the poster while the image loads.
    expect(posterImage(container)).toHaveAttribute("alt", "");
    expect(screen.getByTitle("IMDb")).toHaveAttribute(
      "href",
      "https://www.imdb.com/title/tt0133093/",
    );
    expect(screen.queryByTitle("Open Database Record")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Delete Item from Database")).not.toBeInTheDocument();
    // Nothing is stored yet: no section has a status or anything to forget.
    expect(container.querySelector(".detail-sections [data-status]")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Clear/ })).not.toBeInTheDocument();
  });

  it("draws each section's status in the sidebar's tones, its icon clearing what it holds", () => {
    selectedState.selectItem(
      mediaItem({
        id: 7,
        title: "The Matrix",
        art_status: "partial",
        poster_status: "complete",
        poster_url: "https://image.tmdb.org/t/p/original/a.jpg",
        background_status: "missing",
        theme_status: "missing",
      }),
    );
    selectedState.mode = "monitor";
    renderWithQueryClient(DetailPanel);
    const tone = (el: HTMLElement) => el.querySelector(".status-icon")?.getAttribute("data-status");

    // Something to forget: the icon is its own button.
    expect(tone(screen.getByRole("button", { name: "Clear all art" }))).toBe("warning");
    expect(tone(screen.getByRole("button", { name: "Clear poster" }))).toBe("success");
    // Nothing to forget: the icon belongs to the tab that opens the section.
    expect(screen.queryByRole("button", { name: "Clear background" })).not.toBeInTheDocument();
    expect(tone(screen.getByRole("tab", { name: "Background" }))).toBe("danger");
    expect(screen.queryByRole("button", { name: "Clear theme" })).not.toBeInTheDocument();
    expect(tone(screen.getByRole("tab", { name: "Themes" }))).toBe("danger");
  });

  it("offers the record controls once the item is stored", () => {
    selectedState.selectItem(mediaItem({ id: 7, title: "The Matrix" }));
    selectedState.mode = "monitor";
    renderWithQueryClient(DetailPanel);

    expect(screen.getByTitle("Open Database Record")).toBeInTheDocument();
    expect(screen.getByTitle("Delete Item from Database")).toBeInTheDocument();
  });
});

describe("DetailPanel poster", () => {
  beforeEach(() => {
    queryClient.clear();
    publicDatasetState.reset();
  });

  it("follows selections and clears, and shows the placeholder for a broken image", async () => {
    const chosen = mediaItem({
      id: 7,
      title: "Chosen",
      folder_path: null,
      poster_url: "https://image.tmdb.org/t/p/original/a.jpg",
    });
    selectedState.selectItem(chosen);
    selectedState.mode = "monitor";
    const { container } = renderWithQueryClient(DetailPanel);
    const poster = () => posterImage(container);
    expect(poster()).toHaveAttribute("src", chosen.poster_url);

    selectedState.updateItemData({
      ...chosen,
      poster_url: "https://image.tmdb.org/t/p/original/b.jpg",
    });
    await waitFor(() =>
      expect(poster()).toHaveAttribute("src", "https://image.tmdb.org/t/p/original/b.jpg"),
    );

    await fireEvent.error(poster()!);
    await waitFor(() => expect(poster()).toBeNull());

    selectedState.updateItemData({
      ...chosen,
      poster_url: "https://image.tmdb.org/t/p/original/c.jpg",
    });
    await waitFor(() =>
      expect(poster()).toHaveAttribute("src", "https://image.tmdb.org/t/p/original/c.jpg"),
    );

    selectedState.updateItemData({ ...chosen, poster_url: null });
    await waitFor(() => expect(poster()).toBeNull());
  });
});

describe("DetailPanel images", () => {
  beforeEach(() => {
    queryClient.clear();
    publicDatasetState.reset();
  });

  it("shows the poster by the sidebar's URL and loads it before the background", () => {
    settingsState.show_background_image = true;
    selectedState.selectItem(
      mediaItem({
        id: 7,
        title: "Local",
        folder_path: "/movies/Local",
        poster_hash: "p1",
        background_hash: "b1",
      }),
    );
    selectedState.mode = "monitor";
    const { container } = renderWithQueryClient(DetailPanel);

    // The original file the sidebar row loaded, so it is already in the cache.
    const poster = posterImage(container);
    expect(poster).toHaveAttribute("src", "/api/library/items/7/local-image/poster?t=p1");
    expect(poster).toHaveAttribute("fetchpriority", "high");
    const background = container.querySelector(".detail-background img");
    expect(background).toHaveAttribute(
      "src",
      "/api/library/items/7/local-image/background?t=b1&size=display",
    );
    expect(background).toHaveAttribute("fetchpriority", "low");
  });
});

describe("DetailPanel image changes", () => {
  beforeEach(() => {
    queryClient.clear();
    publicDatasetState.reset();
    artPreviewState.reset();
    settingsState.show_background_image = true;
  });

  const local = (id: number, title: string, hash: string) =>
    mediaItem({
      id,
      title,
      folder_path: `/movies/${title}`,
      poster_hash: hash,
      background_hash: hash,
    });

  it("never shows the previous item's art while the next item's loads", async () => {
    selectedState.selectItem(local(7, "First", "a"));
    selectedState.mode = "monitor";
    const { container } = renderWithQueryClient(DetailPanel);
    const firstPoster = posterImage(container);
    const firstBackground = container.querySelector(".detail-background img");

    selectedState.selectItem(local(8, "Second", "b"));
    await tick();

    // New elements: a reused image keeps its old picture until the new one loads.
    expect(firstPoster).not.toBeInTheDocument();
    expect(firstBackground).not.toBeInTheDocument();
    expect(posterImage(container)).toHaveAttribute(
      "src",
      "/api/library/items/8/local-image/poster?t=b",
    );
  });

  it("shows a chosen poster at once, then the file in the same image", async () => {
    const item = local(7, "Chosen", "old");
    selectedState.selectItem(item);
    selectedState.mode = "monitor";
    const { container } = renderWithQueryClient(DetailPanel);
    const poster = posterImage(container);

    artPreviewState.show(item, "poster", "https://images.test/preview.jpg", "job-1");
    await tick();
    expect(poster).toHaveAttribute("src", "https://images.test/preview.jpg");

    // The same element keeps the preview on screen until the file has loaded.
    const downloaded = { ...item, poster_hash: "new" };
    selectedState.updateItemData(downloaded);
    artPreviewState.itemUpdated(downloaded);
    await tick();
    expect(posterImage(container)).toBe(poster);
    expect(poster).toHaveAttribute("src", "/api/library/items/7/local-image/poster?t=new");
  });
});

describe("DetailPanel record actions", () => {
  const firefly = mediaItem({ id: 7, media_type: "show", title: "Firefly" });
  const alien = mediaItem({
    id: 8,
    title: "Alien",
    poster_url: "https://images.test/poster.jpg",
    youtube_id: "abc123",
  });

  beforeEach(async () => {
    queryClient.clear();
    vi.resetAllMocks();
    confirmAction.mockResolvedValue(true);
    refreshItem.mockResolvedValue(undefined);
    invalidateSeasons.mockResolvedValue(undefined);
    getSeasons.mockResolvedValue({
      data: [
        season({ id: 1, season_num: 1, poster_url: "https://x/1.jpg" }),
        season({ id: 2, season_num: 2, poster_url: "https://x/2.jpg" }),
      ],
    });
    selectedState.mode = "art";
    await navigate("/movies", { replace: true });
  });

  it("forgets every season poster with one request", async () => {
    clearArt.mockResolvedValue({ data: { status: "cleared" } });
    selectedState.selectItem(firefly);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(await screen.findByRole("button", { name: "Clear seasons" }));

    await waitFor(() => expect(invalidateSeasons).toHaveBeenCalledWith(7));
    expect(clearArt).toHaveBeenCalledTimes(1);
    expect(clearArt).toHaveBeenCalledWith(
      expect.objectContaining({ path: { item_id: 7, art_type: "season_poster" } }),
    );
    expect(clearArt.mock.calls[0]?.[0]).not.toHaveProperty("query");
    expect(refreshItem).toHaveBeenCalledWith(7);
  });

  it("forgets one artwork type and refreshes only the item", async () => {
    clearArt.mockResolvedValue({ data: { status: "cleared" } });
    selectedState.selectItem(alien);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByRole("button", { name: "Clear poster" }));

    await waitFor(() => expect(refreshItem).toHaveBeenCalledWith(8));
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Forget the saved poster selection?", destructive: true }),
    );
    expect(clearArt).toHaveBeenCalledWith(
      expect.objectContaining({ path: { item_id: 8, art_type: "poster" } }),
    );
    expect(invalidateSeasons).not.toHaveBeenCalled();
  });

  it("forgets every artwork selection with one request", async () => {
    clearAllArt.mockResolvedValue({ data: { status: "cleared" } });
    selectedState.selectItem(alien);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByRole("button", { name: "Clear all art" }));

    await waitFor(() => expect(invalidateSeasons).toHaveBeenCalledWith(8));
    expect(clearAllArt).toHaveBeenCalledWith(expect.objectContaining({ path: { item_id: 8 } }));
    expect(refreshItem).toHaveBeenCalledWith(8);
  });

  it("changes nothing when a confirmation is declined", async () => {
    confirmAction.mockResolvedValue(false);
    selectedState.selectItem(alien);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByRole("button", { name: "Clear all art" }));
    await fireEvent.click(screen.getByRole("button", { name: "Clear theme" }));
    await fireEvent.click(screen.getByTitle("Delete Item from Database"));

    await waitFor(() => expect(confirmAction).toHaveBeenCalledTimes(3));
    expect(clearAllArt).not.toHaveBeenCalled();
    expect(clearTheme).not.toHaveBeenCalled();
    expect(deleteItem).not.toHaveBeenCalled();
  });

  it("forgets the theme selection", async () => {
    clearTheme.mockResolvedValue({ data: { status: "cleared" } });
    selectedState.selectItem(alien);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByRole("button", { name: "Clear theme" }));

    await waitFor(() => expect(refreshItem).toHaveBeenCalledWith(8));
    expect(clearTheme).toHaveBeenCalledWith(expect.objectContaining({ path: { item_id: 8 } }));
  });

  it("reports a failed action and leaves the item as it was", async () => {
    clearTheme.mockRejectedValue(new ApiError("Theme is being downloaded", 409));
    selectedState.selectItem(alien);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByRole("button", { name: "Clear theme" }));

    expect(await screen.findByText("Theme is being downloaded")).toBeInTheDocument();
    expect(refreshItem).not.toHaveBeenCalled();
  });

  it("toggles monitoring with the server's answer", async () => {
    setMonitored.mockResolvedValue({ data: { monitored: false } });
    selectedState.selectItem(alien);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByTitle("Monitored - click to unmonitor"));

    await waitFor(() =>
      expect(upsertLibraryItem).toHaveBeenCalledWith({ ...alien, monitored: false }),
    );
    expect(setMonitored).toHaveBeenCalledWith(
      expect.objectContaining({ path: { item_id: 8 }, body: { monitored: false } }),
    );
  });

  it("removes a show from Overture and returns to the shows library", async () => {
    deleteItem.mockResolvedValue({ data: { status: "deleted" } });
    selectedState.selectItem(firefly);
    renderWithQueryClient(DetailPanel);

    await fireEvent.click(screen.getByTitle("Delete Item from Database"));

    await waitFor(() => expect(route.pathname).toBe("/shows"));
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Remove Firefly from Overture?" }),
    );
    expect(deleteItem).toHaveBeenCalledWith(expect.objectContaining({ path: { item_id: 7 } }));
  });
});
