import { screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type { DownloadJobEvent } from "../../../generated/rest/types.gen";
import AssetDownloads from "../../../lib/components/AssetDownloads.svelte";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { renderWithQueryClient } from "../../helpers/render";

const activeJob: DownloadJobEvent = {
  job: {
    id: "job-1",
    kind: "download",
    status: "progress",
    target: {
      target_type: "item",
      source: null,
      job_type: "art",
      media_item_id: 1,
      season_id: null,
      art_type: "poster",
      title: "Movie Poster",
    },
    error: null,
  },
  percent: 45,
  stage: "downloading",
  step: 1,
  steps: 3,
  unchanged: null,
};

describe("AssetDownloads", () => {
  beforeEach(() => {
    downloadState.replaceSnapshot([]);
  });

  it("renders nothing when there are no active downloads", () => {
    const { container } = renderWithQueryClient(AssetDownloads);
    expect(container.firstElementChild).toBeNull();
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("lists each lane's running downloads under its own heading", () => {
    downloadState.replaceSnapshot([activeJob]);
    renderWithQueryClient(AssetDownloads);
    expect(screen.getByRole("region", { name: "Art downloads" })).toHaveTextContent("Movie Poster");
    expect(screen.getByText("Downloading 1/3")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Theme downloads" })).toBeNull();
  });
});
