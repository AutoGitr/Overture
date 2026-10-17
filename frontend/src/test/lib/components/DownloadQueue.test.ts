import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import DownloadQueue from "../../../lib/components/DownloadQueue.svelte";
import { type DownloadJob, downloadState } from "../../../lib/stores/downloadState.svelte";

function job(overrides: Partial<DownloadJob> = {}): DownloadJob {
  return {
    job_id: "job-1",
    media_item_id: 1,
    collection_server_id: null,
    media_type: "movie",
    title: "Alien",
    job_type: "art",
    art_type: "poster",
    season_id: null,
    percent: 42.4,
    stage: "downloading",
    status: "running",
    ...overrides,
  };
}

describe("DownloadQueue", () => {
  afterEach(() => {
    downloadState.loadingPending = false;
    downloadState.pendingError = "";
  });

  it("lists each queued download with its stage and rounded progress", () => {
    render(DownloadQueue, {
      jobs: [job(), job({ job_id: "job-2", title: "", art_type: null, percent: 0 })],
    });

    expect(screen.getByText("Alien")).toBeInTheDocument();
    expect(screen.getByText("poster")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Queued download")).toBeInTheDocument();
    expect(screen.getAllByText("downloading")).toHaveLength(2);
  });

  it("says while the queued downloads load", () => {
    downloadState.loadingPending = true;

    render(DownloadQueue, { jobs: [] });

    expect(screen.getByRole("status")).toHaveTextContent("Loading queued downloads...");
  });

  it("retries queued downloads that failed to load", async () => {
    downloadState.pendingError = "Could not load queued downloads. Please retry.";
    const loadPending = vi.spyOn(downloadState, "loadPending").mockResolvedValue(undefined);

    render(DownloadQueue, { jobs: [] });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not load queued downloads. Please retry.",
    );
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(loadPending).toHaveBeenCalledOnce();
  });
});
