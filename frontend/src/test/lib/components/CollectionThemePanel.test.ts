import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCollectionOptions,
  listCollectionsOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionDetail } from "../../../generated/rest/types.gen";
import CollectionThemePanel from "../../../lib/components/CollectionThemePanel.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { navigate } from "../../../lib/router/routes";
import { notificationState } from "../../../lib/stores/notificationState.svelte";
import { collectionDetail as collection } from "../../helpers/fixtures";
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
vi.mock("../../../lib/stores/downloadState.svelte", async (importOriginal) => ({
  ...(await importOriginal()),
  downloadState: { getCollectionJob, trackQueuedCollectionJob },
}));

const starWars = collection({ id: 1, title: "Star Wars", server_type: "plex" });
let shown: CollectionDetail = starWars;

function show(coll: CollectionDetail) {
  shown = coll;
}

function renderPanel() {
  return renderWithQueryClient(CollectionThemePanel, { collection: shown });
}

/** The panel as its route shows it, following the cached collections list. */
async function renderPage() {
  queryClient.setQueryData(listCollectionsOptions({ query: { media_type: "movie" } }).queryKey, [
    shown,
  ]);
  queryClient.setQueryData(
    getCollectionOptions({ path: { collection_id: shown.id }, query: { media_type: "movie" } })
      .queryKey,
    shown,
  );
  await navigate("/movies/collections/:collectionSlug", {
    params: { collectionSlug: String(shown.id) },
  });
  return renderWithQueryClient(CollectionPage);
}

function cachedCollection() {
  return queryClient.getQueryData<CollectionDetail[]>(
    listCollectionsOptions({ query: { media_type: "movie" } }).queryKey,
  )?.[0];
}

function toasts() {
  return notificationState.toasts.map((toast) => toast.message);
}

describe("CollectionThemePanel search", () => {
  beforeEach(() => {
    queryClient.clear();
    show(collection({ id: 1, title: "Star Wars" }));
    vi.resetAllMocks();
    searchYoutube.mockResolvedValue({ data: { results: [] } });
    setCollectionTheme.mockResolvedValue({ data: { job_id: "col-theme-job" } });
  });

  it("switches search button label to Select when input is a YouTube URL and selects directly on click", async () => {
    renderPanel();

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
          path: { collection_id: 1 },
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
    show({
      ...starWars,
      theme_status: "complete",
      has_theme: true,
      youtube_id: "abc12345678",
    });

    renderPanel();

    expect(screen.getByRole("link", { name: /youtu\.be\/abc12345678/ })).toHaveAttribute(
      "href",
      "https://youtu.be/abc12345678",
    );
  });

  it("says a theme is assigned when its source is unknown", () => {
    show({ ...starWars, theme_status: "complete", has_theme: true });

    renderPanel();

    expect(screen.getByText("Theme assigned")).toBeInTheDocument();
  });

  it("shows a running theme job's progress and holds other changes", () => {
    getCollectionJob.mockReturnValue({
      status: "running",
      stage: "downloading",
      step: 2,
      steps: 4,
      percent: 41.6,
    });
    show({ ...starWars, theme_status: "complete", has_theme: true });

    renderPanel();

    expect(screen.getByText("Theme job running: Downloading 2/4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear theme" })).toBeDisabled();
  });

  it("removes the theme from the media server once confirmed", async () => {
    deleteCollectionTheme.mockResolvedValue({
      data: { has_theme: false, theme_status: "missing" },
    });
    show({
      ...starWars,
      theme_status: "complete",
      has_theme: true,
      youtube_id: "abc12345678",
    });
    await renderPage();

    await fireEvent.click(await screen.findByRole("button", { name: "Clear theme" }));
    expect((await answerConfirmation(true)).title).toBe("Remove the collection theme?");

    await waitFor(() =>
      expect(cachedCollection()).toMatchObject({
        has_theme: false,
        youtube_id: null,
        theme_status: "missing",
      }),
    );
    expect(deleteCollectionTheme).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { collection_id: 1 },
        query: { media_type: "movie" },
      }),
    );
  });

  it("toggles monitoring with the server's answer and reports a failure", async () => {
    setCollectionMonitored.mockResolvedValueOnce({ data: { monitored: false } });
    show({ ...starWars, monitored: true });
    await renderPage();

    await fireEvent.click(await screen.findByTitle("Monitored - click to unmonitor"));

    await waitFor(() => expect(cachedCollection()?.monitored).toBe(false));
    expect(setCollectionMonitored).toHaveBeenCalledWith(
      expect.objectContaining({ body: { monitored: false } }),
    );

    setCollectionMonitored.mockRejectedValueOnce(new ApiError("Server unreachable", 503));
    await fireEvent.click(screen.getByTitle("Unmonitored - click to monitor"));

    await waitFor(() => expect(toasts()).toContain("Server unreachable"));
    expect(cachedCollection()?.monitored).toBe(false);
  });

  it("reports a theme the server refused and allows another choice", async () => {
    setCollectionTheme.mockRejectedValue(new ApiError("Video unavailable", 422));
    show(starWars);
    renderPanel();
    const input = await screen.findByLabelText("Search collection themes");

    await fireEvent.input(input, { target: { value: "https://youtu.be/abc12345678" } });
    await fireEvent.click(screen.getByRole("button", { name: "Select" }));

    await waitFor(() => expect(toasts()).toContain("Video unavailable"));
    expect(trackQueuedCollectionJob).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Select" })).toBeEnabled();
  });

  it("tracks the chosen theme's download", async () => {
    setCollectionTheme.mockResolvedValue({ data: { job_id: "job-1" } });
    show(starWars);
    await renderPage();
    const input = await screen.findByLabelText("Search collection themes");

    await fireEvent.input(input, { target: { value: "https://youtu.be/abc12345678" } });
    await fireEvent.click(screen.getByRole("button", { name: "Select" }));
    await waitFor(() =>
      expect(trackQueuedCollectionJob).toHaveBeenCalledWith({
        jobId: "job-1",
        collectionId: 1,
        title: "Star Wars",
      }),
    );
  });
});

describe("Jellyfin collection themes", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.resetAllMocks();
    searchYoutube.mockResolvedValue({ data: { results: [] } });
  });
  it("offers catalog themes when Jellyfin's collection folder is writable", async () => {
    show(
      collection({
        server_type: "jellyfin",
        theme_unavailable: null,
        youtube_id_overturedb: "overture123",
        youtube_id_themerrdb: "themerr12345",
      }),
    );
    renderPanel();
    expect(await screen.findByLabelText("Search collection themes")).toBeInTheDocument();
    expect(screen.getByText("OvertureDB", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.getByText("ThemerrDB", { selector: ".badge" })).toBeInTheDocument();
  });
  it("shows the reason themes cannot be written", () => {
    show(
      collection({ server_type: "jellyfin", theme_unavailable: "Set JELLYFIN_COLLECTIONS_PATH" }),
    );
    renderPanel();
    expect(screen.getByText("Set JELLYFIN_COLLECTIONS_PATH")).toBeInTheDocument();
    expect(screen.queryByLabelText("Search collection themes")).toBeNull();
  });
});
