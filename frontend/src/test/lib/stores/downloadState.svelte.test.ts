import { flushSync } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DownloadJobEvent, DownloadStatus } from "../../../generated/ws";
import { downloadStageLabel, downloadState } from "../../../lib/stores/downloadState.svelte";
import { libraryGate } from "../../../lib/stores/libraryGate.svelte";
import { OPERATIONS } from "../../../lib/stores/operations";
import { matchState, themeJobState } from "../../../lib/stores/bulkJobState.svelte";

const { notify } = vi.hoisted(() => ({ notify: { error: vi.fn(), success: vi.fn() } }));
vi.mock("../../../lib/stores/notificationState.svelte", () => ({ notify }));

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
    step: null,
    steps: null,
    unchanged: null,
    job: {
      id,
      kind: "download",
      status,
      target: {
        target_type: "item",
        source: null,
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
  error?: { message: string } | null;
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

  it("announces a collection theme once its download completes", () => {
    const target = {
      target_type: "collection_theme",
      source: null,
      collection_id: 1,
      title: "Star Wars",
    } as const;
    const event = (status: DownloadStatus): DownloadJobEvent => ({
      percent: null,
      stage: null,
      step: null,
      steps: null,
      unchanged: null,
      job: { id: "theme", kind: "download", status, target, error: null },
    });
    downloadState.trackQueuedCollectionJob({
      jobId: "theme",
      collectionId: 1,
      title: "Star Wars",
    });

    downloadState.handleFinished(event("cancelled"));
    expect(notify.success).not.toHaveBeenCalled();

    downloadState.handleFinished(event("completed"));
    expect(notify.success).toHaveBeenCalledExactlyOnceWith("Theme applied to Star Wars.");
    expect(downloadState.isDownloadingCollection(1)).toBe(false);
  });

  it("lists the running downloads of one lane", () => {
    downloadState.replaceSnapshot([
      itemEvent("job-art", 10, "started"),
      itemEvent("job-theme", 11, "started", null, { title: "Firefly", jobType: "theme" }),
    ]);

    expect(downloadState.lane("art").running.map((job) => job.job_id)).toEqual(["job-art"]);
    expect(downloadState.lane("theme").running.map((job) => job.title)).toEqual(["Firefly"]);
  });

  it("hands a finished download's row to the next one in its lane", () => {
    downloadState.replaceSnapshot([
      itemEvent("first", 10, "started"),
      itemEvent("second", 11, "started"),
      itemEvent("theme", 12, "started", null, { jobType: "theme" }),
    ]);
    const slots = () => downloadState.lane("art").running.map((job) => [job.job_id, job.slot]);
    expect(slots()).toEqual([
      ["first", 0],
      ["second", 1],
    ]);

    downloadState.handleFinished(itemEvent("first", 10, "completed"));
    downloadState.handleProgress(itemEvent("second", 11, "progress", 50));
    downloadState.handleStarted(itemEvent("third", 13, "started"));

    expect(slots()).toEqual([
      ["third", 0],
      ["second", 1],
    ]);
    expect(downloadState.lane("theme").running.map((job) => job.slot)).toEqual([0]);
  });

  it("tracks pending downloads separately from the bulk workflows", () => {
    matchState.reset();
    themeJobState.reset();
    const collection: DownloadJobEvent = {
      ...itemEvent("collection", 1, "pending"),
      job: {
        id: "collection",
        kind: "download",
        status: "pending",
        target: {
          target_type: "collection_theme",
          source: null,
          collection_id: 1,
          title: "Movies",
        },
        error: null,
      },
    };
    downloadState.replaceSnapshot([itemEvent("art", 10, "pending"), collection]);

    expect(downloadState.lane("art")).toEqual({ running: [], waiting: 1 });
    expect(downloadState.lane("theme")).toEqual({ running: [], waiting: 1 });
    expect(OPERATIONS.assets.running).toBe(false);
    expect(OPERATIONS.assets.hasRun).toBe(false);
    expect(libraryGate.blocked("sync")).toContain("downloads");

    downloadState.handleFinished(itemEvent("art", 10, "cancelled"));
    downloadState.handleFinished({
      ...collection,
      job: { ...collection.job, status: "cancelled" },
    });
    expect(OPERATIONS.assets.running).toBe(false);
    expect(OPERATIONS.assets.hasRun).toBe(false);
    expect(libraryGate.blocked("sync")).toBeNull();
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

  it("shows a failure briefly, then removes it", () => {
    vi.useFakeTimers();
    downloadState.handleFailed(itemEvent("job-2", 11, "failed"));

    expect(downloadState.getJobsForItem(11)[0]?.stage).toBe("failed");
    expect(notify.error).toHaveBeenLastCalledWith("failed", {
      title: "Couldn't download the poster for Alien",
    });

    vi.advanceTimersByTime(5000);

    expect(downloadState.getJobsForItem(11)).toEqual([]);
  });

  it("prefers a failure's typed message", () => {
    vi.useFakeTimers();
    downloadState.handleFailed(
      itemEvent("job-typed", 12, "failed", null, {
        error: { message: "typed failed" },
      }),
    );

    expect(downloadState.getJobsForItem(12)[0]?.stage).toBe("typed failed");
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

  it("labels a download by its stage, with its step when it reports one", () => {
    downloadState.replaceSnapshot([
      { ...itemEvent("a", 1, "progress", 60), stage: "transcoding", step: 3, steps: 4 },
      itemEvent("b", 2, "started"),
    ]);
    const [running] = downloadState.getJobsForItem(1);
    const [starting] = downloadState.getJobsForItem(2);
    expect(running && downloadStageLabel(running)).toBe("Transcoding 3/4");
    expect(starting && downloadStageLabel(starting)).toBe("Starting");
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
      collectionId: 1,
      title: "Saga",
    });
    downloadState.handleFailed({
      percent: null,
      stage: null,
      step: null,
      steps: null,
      unchanged: null,
      job: {
        id: "old",
        kind: "download",
        status: "failed",
        target: {
          target_type: "collection_theme",
          source: null,
          collection_id: 1,
          title: "Saga",
        },
        error: null,
      },
    });
    downloadState.trackQueuedCollectionJob({
      jobId: "new",
      collectionId: 1,
      title: "Saga",
    });

    expect(downloadState.getCollectionJob(1)?.job_id).toBe("new");
    expect(downloadState.isDownloadingCollection(1)).toBe(true);
  });
});
