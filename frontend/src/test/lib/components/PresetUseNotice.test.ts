import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PresetUseRead } from "../../../generated/rest/types.gen";
import PresetUseNotice from "../../../lib/components/PresetUseNotice.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";

const USE: PresetUseRead = {
  preset_id: "holidays",
  preset_title: "Holidays",
  item: "Christmas",
  collection_id: 12,
  group: null,
  changes: [],
  gone: false,
};

function mockUses(use: PresetUseRead) {
  return mockFetchRoutes({
    "/api/collections/presets/uses": { uses: [use], error: null },
    "/api/collections/presets/uses/review": { ...use, changes: [] },
  });
}

describe("PresetUseNotice", () => {
  beforeEach(() => queryClient.clear());

  it("names the preset a collection came from while OvertureDB leaves it as it is", async () => {
    mockUses(USE);
    renderWithQueryClient(PresetUseNotice, {
      subject: { collection_id: 12 },
      onreviewed: vi.fn(),
    });
    expect(
      await screen.findByText(/From OvertureDB's Holidays preset: Christmas/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("takes OvertureDB's changes, then loads them into the form", async () => {
    const { calls } = mockUses({ ...USE, changes: ["criteria", "active dates"] });
    const onreviewed = vi.fn(() => Promise.resolve());
    renderWithQueryClient(PresetUseNotice, { subject: { collection_id: 12 }, onreviewed });

    expect(await screen.findByText(/has new criteria, active dates/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Take changes" }));

    await waitFor(() => expect(onreviewed).toHaveBeenCalled());
    const review = calls.find((call) => call.url === "/api/collections/presets/uses/review");
    expect(JSON.parse(String(review?.init.body))).toEqual({ collection_id: 12, take: true });
  });

  it("keeps a group's set as it is when asked to", async () => {
    const { calls } = mockUses({
      ...USE,
      collection_id: null,
      group: "Decades",
      changes: ["what the set makes"],
    });
    renderWithQueryClient(PresetUseNotice, {
      subject: { group: "Decades" },
      onreviewed: () => Promise.resolve(),
    });
    await fireEvent.click(await screen.findByRole("button", { name: "Keep mine" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/collections/presets/uses/review")).toBe(true),
    );
    const review = calls.find((call) => call.url === "/api/collections/presets/uses/review");
    expect(JSON.parse(String(review?.init.body))).toEqual({ group: "Decades", take: false });
  });

  it("offers to stop tracking an item OvertureDB no longer publishes", async () => {
    mockUses({ ...USE, gone: true });
    renderWithQueryClient(PresetUseNotice, {
      subject: { collection_id: 12 },
      onreviewed: () => Promise.resolve(),
    });
    expect(await screen.findByText("OvertureDB no longer publishes it")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop tracking" })).toBeInTheDocument();
  });
});
