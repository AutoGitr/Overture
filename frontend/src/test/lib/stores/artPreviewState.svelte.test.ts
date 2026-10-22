import { beforeEach, describe, expect, it } from "vitest";
import { projectRealtimeMessage } from "../../../lib/realtime/projector";
import { artPreviewState } from "../../../lib/stores/artPreviewState.svelte";
import { itemDownload, mediaItem, wsMessage } from "../../helpers/fixtures";

const before = mediaItem({ id: 1, folder_path: "/movies/A", poster_hash: "old" });
const preview = "https://images.test/preview.jpg";

type DownloadEnd = "download.completed" | "download.failed" | "download.cancelled";

function downloadEvent(event: DownloadEnd, jobId: string, unchanged: boolean | null = null) {
  const status =
    event === "download.completed"
      ? "completed"
      : event === "download.failed"
        ? "failed"
        : "cancelled";
  return wsMessage(event, itemDownload(jobId, 1, status, { unchanged }));
}

describe("art previews", () => {
  beforeEach(() => {
    artPreviewState.reset();
  });

  it("stands in for the art it replaces until the item shows the new file", () => {
    artPreviewState.show(before, "poster", preview, "job-1");

    expect(artPreviewState.previewFor(before, "poster")).toBe(preview);
    expect(artPreviewState.previewFor(before, "background")).toBeNull();

    // Other fields changing leaves the preview in place.
    artPreviewState.itemUpdated({ ...before, title: "Renamed" });
    expect(artPreviewState.previewFor(before, "poster")).toBe(preview);

    const downloaded = { ...before, poster_hash: "new" };
    artPreviewState.itemUpdated(downloaded);
    expect(artPreviewState.previewFor(downloaded, "poster")).toBeNull();
    // Gone for good: art that later returns to the old file is the file.
    expect(artPreviewState.previewFor(before, "poster")).toBeNull();
  });

  it("is never shown over art the item already moved on from", () => {
    artPreviewState.show(before, "poster", preview, "job-1");

    expect(artPreviewState.previewFor({ ...before, poster_hash: "new" }, "poster")).toBeNull();
  });

  it.each([
    ["download.failed", null],
    ["download.cancelled", null],
    ["download.completed", true],
  ] as const)("goes when %s brings no new art", (event, unchanged) => {
    artPreviewState.show(before, "poster", preview, "job-1");

    projectRealtimeMessage(downloadEvent(event, "job-1", unchanged));

    expect(artPreviewState.previewFor(before, "poster")).toBeNull();
  });

  it("waits for the new file after a download that wrote it", () => {
    artPreviewState.show(before, "poster", preview, "job-1");
    artPreviewState.show(before, "background", preview, "job-2");

    projectRealtimeMessage(downloadEvent("download.completed", "job-1", false));
    projectRealtimeMessage(downloadEvent("download.failed", "job-2"));

    expect(artPreviewState.previewFor(before, "poster")).toBe(preview);
    expect(artPreviewState.previewFor(before, "background")).toBeNull();
  });
});
