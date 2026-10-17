import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CollectionThemePanel from "../../../lib/components/CollectionThemePanel.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { collectionState } from "../../../lib/stores/collectionState.svelte";
import { ApiError } from "../../../lib/rest/transport";
import { notificationState } from "../../../lib/stores/notificationState.svelte";
import { collection } from "../../helpers/fixtures";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";

const {
  deleteCollectionTheme,
  getCollectionJob,
  searchYoutube,
  setCollectionMonitored,
  setCollectionTheme,
  trackQueuedCollectionJob,
} = vi.hoisted(() => ({
  deleteCollectionTheme: vi.fn(),
  getCollectionJob: vi.fn(),
  searchYoutube: vi.fn(),
  setCollectionMonitored: vi.fn(),
  setCollectionTheme: vi.fn(),
  trackQueuedCollectionJob: vi.fn(),
}));

vi.mock("../../../generated/rest/sdk.gen", () => ({
  deleteCollectionTheme,
  searchYoutube,
  setCollectionMonitored,
  setCollectionTheme,
}));
vi.mock("../../../lib/stores/downloadState.svelte", () => ({
  downloadState: { getCollectionJob, trackQueuedCollectionJob },
}));

const starWars = collection({ id: "coll-1", title: "Star Wars", server_type: "plex" });

function toasts() {
  return notificationState.toasts.map((toast) => toast.message);
}

describe("CollectionThemePanel search", () => {
  beforeEach(() => {
    queryClient.clear();
    collectionState.selectCollection(collection({ id: "coll-1", title: "Star Wars" }));
    vi.resetAllMocks();
    searchYoutube.mockResolvedValue({ data: { results: [] } });
    setCollectionTheme.mockResolvedValue({ data: { job_id: "col-theme-job" } });
  });

  it("switches search button label to Select when input is a YouTube URL and selects directly on click", async () => {
    renderWithQueryClient(CollectionThemePanel);

    // Wait for the initial automatic search to settle
    expect(await screen.findByRole("button", { name: "Search" })).toBeInTheDocument();
    const input = screen.getByLabelText("Search collection themes");

    await fireEvent.input(input, {
      target: { value: "https://www.youtube.com/watch?v=abc12345678" },
    });
    expect(screen.getByRole("button", { name: "Select" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();

    await fireEvent.input(input, {
      target: { value: "Star Wars theme music" },
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
      expect(setCollectionTheme).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { collection_id: "coll-1" },
          body: { media_type: "movie", youtube_id: "abc12345678" },
        }),
      );
    });
    expect(searchYoutube).not.toHaveBeenCalled();
  });
});

describe("CollectionThemePanel theme state", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.resetAllMocks();
    searchYoutube.mockResolvedValue({ data: { results: [] } });
  });

  it("links the assigned theme's YouTube source", () => {
    collectionState.selectCollection({
      ...starWars,
      theme_status: "complete",
      has_theme: true,
      youtube_id: "abc12345678",
    });

    renderWithQueryClient(CollectionThemePanel);

    expect(screen.getByRole("link", { name: /youtu\.be\/abc12345678/ })).toHaveAttribute(
      "href",
      "https://youtu.be/abc12345678",
    );
  });

  it("says a theme is assigned when its source is unknown", () => {
    collectionState.selectCollection({ ...starWars, theme_status: "complete", has_theme: true });

    renderWithQueryClient(CollectionThemePanel);

    expect(screen.getByText("Theme assigned")).toBeInTheDocument();
  });

  it("shows a running theme job's progress and holds other changes", () => {
    getCollectionJob.mockReturnValue({ status: "running", stage: "downloading", percent: 41.6 });
    collectionState.selectCollection({ ...starWars, theme_status: "complete", has_theme: true });

    renderWithQueryClient(CollectionThemePanel);

    expect(screen.getByText("Theme job running: downloading 42%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear theme" })).toBeDisabled();
  });

  it("removes the theme from the media server once confirmed", async () => {
    deleteCollectionTheme.mockResolvedValue({
      data: { has_theme: false, theme_status: "missing" },
    });
    collectionState.selectCollection({
      ...starWars,
      theme_status: "complete",
      has_theme: true,
      youtube_id: "abc12345678",
    });
    renderWithQueryClient(CollectionThemePanel);

    await fireEvent.click(screen.getByRole("button", { name: "Clear theme" }));
    expect((await answerConfirmation(true)).title).toBe("Remove the collection theme?");

    await waitFor(() =>
      expect(collectionState.selectedCollection).toMatchObject({
        has_theme: false,
        youtube_id: null,
        theme_status: "missing",
      }),
    );
    expect(deleteCollectionTheme).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { collection_id: "coll-1" },
        query: { media_type: "movie" },
      }),
    );
  });

  it("toggles monitoring with the server's answer and reports a failure", async () => {
    setCollectionMonitored.mockResolvedValueOnce({ data: { monitored: false } });
    collectionState.selectCollection({ ...starWars, monitored: true });
    renderWithQueryClient(CollectionThemePanel);

    await fireEvent.click(screen.getByTitle("Monitored - click to unmonitor"));

    await waitFor(() => expect(collectionState.selectedCollection?.monitored).toBe(false));
    expect(setCollectionMonitored).toHaveBeenCalledWith(
      expect.objectContaining({ body: { monitored: false } }),
    );

    setCollectionMonitored.mockRejectedValueOnce(new ApiError("Server unreachable", 503));
    await fireEvent.click(screen.getByTitle("Unmonitored - click to monitor"));

    await waitFor(() => expect(toasts()).toContain("Server unreachable"));
    expect(collectionState.selectedCollection?.monitored).toBe(false);
  });

  it("reports a theme the server refused and allows another choice", async () => {
    setCollectionTheme.mockRejectedValue(new ApiError("Video unavailable", 422));
    collectionState.selectCollection(starWars);
    renderWithQueryClient(CollectionThemePanel);
    const input = await screen.findByLabelText("Search collection themes");

    await fireEvent.input(input, { target: { value: "https://youtu.be/abc12345678" } });
    await fireEvent.click(screen.getByRole("button", { name: "Select" }));

    await waitFor(() => expect(toasts()).toContain("Video unavailable"));
    expect(trackQueuedCollectionJob).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Select" })).toBeEnabled();
  });

  it("confirms once the chosen theme reaches the collection", async () => {
    setCollectionTheme.mockResolvedValue({ data: { job_id: "job-1" } });
    collectionState.selectCollection(starWars);
    renderWithQueryClient(CollectionThemePanel);
    const input = await screen.findByLabelText("Search collection themes");

    await fireEvent.input(input, { target: { value: "https://youtu.be/abc12345678" } });
    await fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() =>
      expect(trackQueuedCollectionJob).toHaveBeenCalledWith({
        jobId: "job-1",
        serverId: "coll-1",
        mediaType: "movie",
        title: "Star Wars",
      }),
    );

    collectionState.selectCollection({
      ...starWars,
      has_theme: true,
      youtube_id: "abc12345678",
      theme_status: "complete",
    });

    await waitFor(() => expect(toasts()).toContain("Theme applied to Star Wars."));
  });
});
