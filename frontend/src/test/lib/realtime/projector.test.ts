import { queryClient } from "../../../lib/rest/queryClient";
import { getPublicDatasetStatusOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  projectRealtimeMessage,
  projectRealtimeSnapshot,
  resetRealtimeProjection,
} from "../../../lib/realtime/projector";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { publicDatasetSyncState, syncState } from "../../../lib/stores/jobStates.svelte";
import {
  itemDownload,
  publicDatasetStatus,
  realtimeSnapshot,
  wsMessage as event,
} from "../../helpers/fixtures";

const { invalidateSchedules } = vi.hoisted(() => ({ invalidateSchedules: vi.fn() }));
vi.mock("../../../lib/rest/cache", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/rest/cache")>()),
  invalidateSchedules,
}));

const download = itemDownload("job-1", 4, "started", { percent: 10, stage: "downloading" });

describe("realtime projection", () => {
  beforeEach(() => {
    resetRealtimeProjection();
    invalidateSchedules.mockResolvedValue(undefined);
  });

  it("follows a download from its start", () => {
    projectRealtimeMessage(event("download.started", download));

    expect(downloadState.getJobsForItem(4)).toEqual([
      expect.objectContaining({ job_id: "job-1", stage: "downloading" }),
    ]);
  });

  it("forgets a job's result once the server cleared it", () => {
    syncState.handleCompleted({ done: 1, total: 1, finished_at: "2026-01-01T00:00:00Z" });

    projectRealtimeMessage(
      event("job.snapshot.cleared", { kind: "sync", finished_at: "2026-01-01T00:00:00Z" }),
    );

    expect(syncState.status).toBe("idle");
  });

  it("re-reads the schedules the server announced as changed", () => {
    projectRealtimeMessage(event("schedules.changed", { kind: "assets" }));

    expect(invalidateSchedules).toHaveBeenCalledWith("assets");
  });

  it("resumes the jobs a continuing snapshot names and forgets the others", () => {
    syncState.handleStarted({ total: 5 });
    publicDatasetSyncState.handleStarted({});

    projectRealtimeSnapshot(
      realtimeSnapshot({
        sequence: 4,
        jobs: [{ event: "sync.progress", data: { done: 2, total: 5 } }],
        downloads: [download],
      }),
      true,
    );

    expect(syncState.running).toBe(true);
    expect(syncState.done).toBe(2);
    expect(publicDatasetSyncState.status).toBe("idle");
    expect(downloadState.activeCount).toBe(1);
  });
});

describe("OvertureDB sync liveness", () => {
  beforeEach(() => publicDatasetSyncState.reset());

  it("stays released once the sync ends, whatever the status broadcast says", () => {
    projectRealtimeMessage(
      event(
        "public-dataset.sync.started",
        { job: { kind: "public_dataset_sync", status: "started" } },
        1,
      ),
    );
    expect(publicDatasetSyncState.running).toBe(true);

    projectRealtimeMessage(
      event(
        "public-dataset.sync.completed",
        {
          job: { kind: "public_dataset_sync", status: "completed" },
          finished_at: "2026-01-01T00:00:00+00:00",
        },
        2,
      ),
    );
    expect(publicDatasetSyncState.running).toBe(false);

    projectRealtimeMessage(
      event(
        "public-dataset.updated",
        publicDatasetStatus({
          last_synced_at: "2026-01-01T00:00:00+00:00",
          last_status: "success",
        }),
        3,
      ),
    );

    expect(publicDatasetSyncState.running).toBe(false);
    expect(queryClient.getQueryData(getPublicDatasetStatusOptions().queryKey)?.last_status).toBe(
      "success",
    );
  });

  it("reports the failure and releases the button", () => {
    projectRealtimeMessage(
      event(
        "public-dataset.sync.started",
        { job: { kind: "public_dataset_sync", status: "started" } },
        1,
      ),
    );
    projectRealtimeMessage(
      event(
        "public-dataset.sync.failed",
        {
          job: {
            kind: "public_dataset_sync",
            status: "failed",
            error: { message: "catalog unreachable" },
          },
        },
        2,
      ),
    );

    expect(publicDatasetSyncState.running).toBe(false);
    expect(publicDatasetSyncState.error).toBe("catalog unreachable");
  });
});
