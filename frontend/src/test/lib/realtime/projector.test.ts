import { queryClient } from "../../../lib/rest/queryClient";
import { getCatalogStatusOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  projectRealtimeMessage,
  projectRealtimeSnapshot,
  resetRealtimeProjection,
} from "../../../lib/realtime/projector";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { notify } from "../../../lib/stores/notificationState.svelte";
import { catalogSyncState, syncState } from "../../../lib/stores/jobStates.svelte";
import {
  catalogStatus,
  catalogSyncEvent,
  itemDownload,
  jobMetadata,
  realtimeSnapshot,
  syncEvent,
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
    syncState.handleCompleted(
      syncEvent({ done: 1, total: 1, finished_at: "2026-01-01T00:00:00Z" }),
    );

    projectRealtimeMessage(
      event("job.snapshot.cleared", { kind: "sync", finished_at: "2026-01-01T00:00:00Z" }),
    );

    expect(syncState.status).toBe("idle");
  });

  it("re-reads the schedules the server announced as changed", () => {
    projectRealtimeMessage(event("schedules.changed", { kind: "assets" }));

    expect(invalidateSchedules).toHaveBeenCalledWith("assets");
  });

  it("restores a finished run from a snapshot without announcing it", () => {
    const success = vi.spyOn(notify, "success");

    projectRealtimeSnapshot(
      realtimeSnapshot({
        jobs: [
          {
            event: "sync.completed",
            data: { done: 1, total: 1, finished_at: "2026-01-01T00:00:00Z" },
          },
        ],
      }),
      false,
    );

    expect(syncState.status).toBe("completed");
    expect(success).not.toHaveBeenCalled();
  });

  it("announces a run that ends live", () => {
    const success = vi.spyOn(notify, "success");

    projectRealtimeMessage(
      event(
        "sync.completed",
        syncEvent({ done: 1, total: 1, finished_at: "2026-01-01T00:00:00Z" }),
      ),
    );

    expect(success).toHaveBeenCalledWith("Library sync finished.");
  });

  it("resumes the jobs a continuing snapshot names and forgets the others", () => {
    syncState.handleStarted(syncEvent({ total: 5 }));
    catalogSyncState.handleStarted(catalogSyncEvent({}));

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
    expect(catalogSyncState.status).toBe("idle");
    expect(downloadState.activeCount).toBe(1);
  });
});

describe("OvertureDB sync liveness", () => {
  beforeEach(() => catalogSyncState.reset());

  it("stays released once the sync ends, whatever the status broadcast says", () => {
    projectRealtimeMessage(
      event(
        "catalog.sync.started",
        catalogSyncEvent({ job: jobMetadata("catalog_sync", "started") }),
        1,
      ),
    );
    expect(catalogSyncState.running).toBe(true);

    projectRealtimeMessage(
      event(
        "catalog.sync.completed",
        catalogSyncEvent({
          job: jobMetadata("catalog_sync", "completed"),
          finished_at: "2026-01-01T00:00:00+00:00",
        }),
        2,
      ),
    );
    expect(catalogSyncState.running).toBe(false);

    projectRealtimeMessage(
      event(
        "catalog.updated",
        catalogStatus({
          last_synced_at: "2026-01-01T00:00:00+00:00",
          last_status: "success",
        }),
        3,
      ),
    );

    expect(catalogSyncState.running).toBe(false);
    expect(queryClient.getQueryData(getCatalogStatusOptions().queryKey)?.last_status).toBe(
      "success",
    );
  });

  it("reports the failure and releases the button", () => {
    projectRealtimeMessage(
      event(
        "catalog.sync.started",
        catalogSyncEvent({ job: jobMetadata("catalog_sync", "started") }),
        1,
      ),
    );
    projectRealtimeMessage(
      event(
        "catalog.sync.failed",
        catalogSyncEvent({
          job: jobMetadata("catalog_sync", "failed", {
            error: { message: "catalog unreachable" },
          }),
        }),
        2,
      ),
    );

    expect(catalogSyncState.running).toBe(false);
    expect(catalogSyncState.error).toBe("catalog unreachable");
  });
});
