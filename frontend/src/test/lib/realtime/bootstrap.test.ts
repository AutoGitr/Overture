import { describe, expect, it, vi } from "vitest";
import { loadRealtimeSnapshot } from "../../../lib/realtime/bootstrap";
import { realtimeStream } from "../../../lib/realtime/stream";
import * as sdk from "../../../generated/rest/sdk.gen";

vi.mock("../../../generated/rest/sdk.gen", () => ({
  getRealtimeSnapshot: vi.fn(),
}));

describe("loadRealtimeSnapshot", () => {
  it("fetches snapshot and applies it to realtimeStream", async () => {
    const applySpy = vi.spyOn(realtimeStream, "applySnapshot").mockImplementation(() => true);
    const mockSnapshot = { timestamp: "2026-01-01T00:00:00Z" };
    vi.mocked(sdk.getRealtimeSnapshot).mockResolvedValueOnce({
      data: mockSnapshot,
      error: undefined,
      request: new Request("http://localhost"),
      response: new Response(),
    } as any);

    const controller = new AbortController();
    await loadRealtimeSnapshot(controller.signal);

    expect(applySpy).toHaveBeenCalledWith(mockSnapshot);
    applySpy.mockRestore();
  });

  it("throws if signal was aborted", async () => {
    const controller = new AbortController();
    controller.abort();

    vi.mocked(sdk.getRealtimeSnapshot).mockResolvedValueOnce({
      data: {},
      error: undefined,
      request: new Request("http://localhost"),
      response: new Response(),
    } as any);

    await expect(loadRealtimeSnapshot(controller.signal)).rejects.toThrow();
  });
});
