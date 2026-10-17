import { flushSync } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DownloadJobEvent, DownloadStatus } from "../../../generated/ws";
import { downloadState } from "../../../lib/stores/downloadState.svelte";

vi.mock("../../../lib/stores/notificationState.svelte", () => ({
  notify: { error: vi.fn() },
}));

function itemEvent(
  id: string,
  mediaItemId: number,
  status: DownloadStatus,
  percent: number | null = null,
  { title = "Alien", jobType = "art", error = null }: ItemEventOptions = {},
): DownloadJobEvent {
  return {
    percent,
    stage: null,
    unchanged: null,
    job: {
      id,
      kind: "download",
      status,
      target: {
        target_type: "item",
        media_item_id: mediaItemId,
        title,
        job_type: jobType,
        art_type: jobType === "art" ? "poster" : null,
        season_id: null,
      },
      error,
    },
  };
}

interface ItemEventOptions {
  title?: string;
  jobType?: "art" | "theme";
  error?: { code: string; message: string } | null;
}

describe("downloadState", () => {
  beforeEach(() => downloadState.replaceSnapshot([]));

  it("tracks a running job's progress and drops it once finished", () => {
    downloadState.replaceSnapshot([itemEvent("job-1", 10, "started")]);
    downloadState.handleProgress({ ...itemEvent("job-1", 10, "progress", 70), stage: "writing" });

    expect(downloadState.activeCount).toBe(1);
    expect(downloadState.isDownloadingType(10, "art", "poster")).toBe(true);
    expect(downloadState.getJobsForItem(10)[0]).toMatchObject({
      title: "Alien",
      percent: 70,
      stage: "writing",
    });

    downloadState.handleFinished(itemEvent("job-1", 10, "completed"));

    expect(downloadState.activeCount).toBe(0);
  });

  it("lists the running downloads of one kind", () => {
    downloadState.replaceSnapshot([
      itemEvent("job-art", 10, "started"),
      itemEvent("job-theme", 11, "started", null, { title: "Firefly", jobType: "theme" }),
    ]);

    expect(downloadState.activeJobsByType("art").map((job) => job.job_id)).toEqual(["job-art"]);
    expect(downloadState.activeJobsByType("theme").map((job) => job.title)).toEqual(["Firefly"]);
  });

  it("exposes an accepted queued job before realtime starts it", () => {
    downloadState.trackQueuedItemJob({
      jobId: "queued-art",
      mediaItemId: 10,
      jobType: "art",
      artType: "poster",
    });

    expect(downloadState.getJobsForItem(10)).toEqual([
      expect.objectContaining({ job_id: "queued-art", stage: "queued", status: "running" }),
    ]);
    expect(downloadState.activeCount).toBe(1);
  });

  it("shows a failure with its job ID briefly, then removes it", () => {
    vi.useFakeTimers();
    downloadState.handleFailed(itemEvent("job-2", 11, "failed"));

    expect(downloadState.getJobsForItem(11)[0]?.stage).toBe("failed (Job ID: job-2)");

    vi.advanceTimersByTime(5000);

    expect(downloadState.getJobsForItem(11)).toEqual([]);
  });

  it("prefers a failure's typed message", () => {
    vi.useFakeTimers();
    downloadState.handleFailed(
      itemEvent("job-typed", 12, "failed", null, {
        error: { code: "error", message: "typed failed" },
      }),
    );

    expect(downloadState.getJobsForItem(12)[0]?.stage).toBe("typed failed (Job ID: job-typed)");
  });

  it("updates an item's downloads only when one of its own changes", () => {
    downloadState.replaceSnapshot([itemEvent("a", 1, "started"), itemEvent("b", 2, "started")]);
    let reads = 0;
    const cleanup = $effect.root(() => {
      $effect(() => {
        downloadState.getJobsForItem(1);
        reads += 1;
      });
    });
    flushSync();
    expect(reads).toBe(1);

    downloadState.handleProgress(itemEvent("b", 2, "progress", 50));
    flushSync();
    expect(reads).toBe(1);

    downloadState.handleProgress(itemEvent("a", 1, "progress", 50));
    flushSync();
    expect(reads).toBe(2);
    expect(downloadState.getJobsForItem(1)[0]?.percent).toBe(50);
    cleanup();
  });

  it("lists a failure until its display time ends, unless the download starts again", () => {
    vi.useFakeTimers();
    downloadState.handleFailed(itemEvent("a", 1, "failed"));
    expect(downloadState.getJobsForItem(1)[0]?.status).toBe("failed");
    expect(downloadState.activeCount).toBe(0);

    downloadState.handleStarted(itemEvent("a", 1, "started"));
    vi.advanceTimersByTime(5000);
    expect(downloadState.getJobsForItem(1)[0]?.status).toBe("running");
    expect(downloadState.isDownloadingType(1, "art", "poster")).toBe(true);

    downloadState.handleFinished(itemEvent("a", 1, "completed"));
    expect(downloadState.getJobsForItem(1)).toEqual([]);
    expect(downloadState.activeCount).toBe(0);
  });

  it("prefers a collection's running download to a failed one", () => {
    vi.useFakeTimers();
    downloadState.trackQueuedCollectionJob({
      jobId: "old",
      serverId: "coll",
      mediaType: "movie",
      title: "Saga",
    });
    downloadState.handleFailed({
      percent: null,
      stage: null,
      unchanged: null,
      job: {
        id: "old",
        kind: "download",
        status: "failed",
        target: {
          target_type: "collection_theme",
          collection_server_id: "coll",
          media_type: "movie",
          title: "Saga",
        },
        error: null,
      },
    });
    downloadState.trackQueuedCollectionJob({
      jobId: "new",
      serverId: "coll",
      mediaType: "movie",
      title: "Saga",
    });

    expect(downloadState.getCollectionJob("coll")?.job_id).toBe("new");
    expect(downloadState.isDownloadingCollection("coll")).toBe(true);
  });
});
