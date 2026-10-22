import { describe, expect, it, vi } from "vitest";
import { clearJobResult } from "../../../lib/utils/jobSnapshots";
import { JOB_STATES } from "../../../lib/realtime/jobs";
import * as sdk from "../../../generated/rest/sdk.gen";

vi.mock("../../../generated/rest/sdk.gen", () => ({
  clearJobSnapshot: vi.fn(),
}));

describe("jobSnapshots", () => {
  it("clears job result when finished_at is present and not stale", async () => {
    const state = JOB_STATES["server_audit"];
    state.finished_at = "2026-01-01T00:00:00Z";
    vi.mocked(sdk.clearJobSnapshot).mockResolvedValueOnce({
      data: { status: "cleared" },
      error: undefined,
      request: new Request("http://localhost"),
      response: new Response(),
    } as any);

    const cleared = await clearJobResult("server_audit");
    expect(cleared).toBe(true);
    expect(state.finished_at).toBeNull();
  });

  it("returns false when snapshot is stale", async () => {
    const state = JOB_STATES["server_audit"];
    state.finished_at = "2026-01-01T00:00:00Z";
    vi.mocked(sdk.clearJobSnapshot).mockResolvedValueOnce({
      data: { status: "stale" },
      error: undefined,
      request: new Request("http://localhost"),
      response: new Response(),
    } as any);

    const cleared = await clearJobResult("server_audit");
    expect(cleared).toBe(false);
  });

  it("resets state directly if finished_at is null", async () => {
    const state = JOB_STATES["server_audit"];
    state.finished_at = null;
    state.total = 10;

    const cleared = await clearJobResult("server_audit");
    expect(cleared).toBe(true);
    expect(state.total).toBeNull();
  });
});
