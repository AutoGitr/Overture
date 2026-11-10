import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import {
  beginAutoAdvance,
  cancelPendingAutoAdvance,
  type AutoAdvanceSettings,
} from "../../../lib/utils/autoAdvance";
import {
  handleRecordSelectionAdvance,
  nextRecordTarget,
  openNextRecord,
  type AdvanceRecord,
  type RecordSlot,
} from "../../../lib/utils/recordAdvance";
import { appSettings } from "../../helpers/fixtures";

vi.mock("../../../lib/router/routes", () => ({
  route: { pathname: "/overturedb/movies/collections/tmdb-1/art/poster" },
  routedItem: () => null,
  routedItemId: () => null,
  routedCollectionId: () => null,
  routedCatalogEntry: () => ({ media_type: "collection", entry_key: "tmdb-1" }),
  goToCatalogEntry: vi.fn(),
  goToCollectionView: vi.fn(),
}));

const settings: AutoAdvanceSettings = {
  workflow: "art_and_themes",
  auto_advance: "slots_and_items",
  auto_advance_skip_completed: false,
};

function record(
  key: string,
  done: Partial<Record<RecordSlot, boolean>> = {},
  slots: RecordSlot[] = ["poster", "background", "theme"],
): AdvanceRecord & { open: Mock<(slot: RecordSlot) => void> } {
  return {
    key,
    slots: slots.map((slot) => ({ slot, complete: !!done[slot] })),
    open: vi.fn<(slot: RecordSlot) => void>(),
  };
}

beforeEach(() => {
  settingsState.load(appSettings(settings));
});

afterEach(() => {
  cancelPendingAutoAdvance();
  sidebarState.records = null;
  sidebarState.walk = null;
  settingsState.reset();
});

describe("next slot of a collection or catalog entry", () => {
  it("moves through art, seasons and the theme in order", () => {
    const show = record("show", {}, ["poster", "background", "season:1", "season:2", "theme"]);
    expect(nextRecordTarget(show, "poster", settings)).toBe("background");
    expect(nextRecordTarget(show, "background", settings)).toBe("season:1");
    expect(nextRecordTarget(show, "season:2", settings)).toBe("theme");
    expect(nextRecordTarget(show, "theme", settings)).toBe("next");
  });

  it("skips complete slots only when asked", () => {
    const row = record("a", { background: true });
    expect(nextRecordTarget(row, "poster", settings)).toBe("background");
    expect(
      nextRecordTarget(row, "poster", { ...settings, auto_advance_skip_completed: true }),
    ).toBe("theme");
  });

  it("follows the workflow and the advance mode", () => {
    const row = record("a");
    expect(nextRecordTarget(row, "background", { ...settings, workflow: "art" })).toBe("next");
    expect(nextRecordTarget(row, "poster", { ...settings, workflow: "themes" })).toBeNull();
    expect(nextRecordTarget(row, "theme", { ...settings, auto_advance: "slots" })).toBeNull();
    expect(nextRecordTarget(row, "poster", { ...settings, auto_advance: "off" })).toBeNull();
  });
});

describe("next row", () => {
  it("opens the next row at its first slot, or its first slot to do", () => {
    const rows = [record("a"), record("b", { poster: true }), record("c")];
    expect(openNextRecord("a", rows, settings)).toBe(true);
    expect(rows[1]!.open).toHaveBeenCalledWith("poster");

    expect(openNextRecord("a", rows, { ...settings, auto_advance_skip_completed: true })).toBe(
      true,
    );
    expect(rows[1]!.open).toHaveBeenLastCalledWith("background");
  });

  it("skips complete rows and stops at the end", () => {
    const skip = { ...settings, auto_advance_skip_completed: true };
    const rows = [
      record("a"),
      record("b", { poster: true, background: true, theme: true }),
      record("c"),
    ];
    expect(openNextRecord("a", rows, skip)).toBe(true);
    expect(rows[1]!.open).not.toHaveBeenCalled();
    expect(rows[2]!.open).toHaveBeenCalledWith("poster");
    expect(openNextRecord("c", rows, skip)).toBe(false);
  });
});

describe("after a save", () => {
  it("advances after the delay, through the rows shown when the save began", () => {
    vi.useFakeTimers();
    const rows = [record("a", {}, ["theme"]), record("b")];
    sidebarState.records = rows;
    const context = beginAutoAdvance();
    sidebarState.records = [];

    handleRecordSelectionAdvance("a", "theme", context);
    expect(rows[1]!.open).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(rows[1]!.open).toHaveBeenCalledWith("poster");
    vi.useRealTimers();
  });

  it("prefers the page's record, which knows each season", () => {
    vi.useFakeTimers();
    const row = record("a", {}, ["poster", "background", "seasons", "theme"]);
    const page = record("a", {}, ["poster", "background", "season:1", "theme"]);
    sidebarState.records = [row];

    handleRecordSelectionAdvance("a", "background", beginAutoAdvance(), page);
    vi.runAllTimers();
    expect(page.open).toHaveBeenCalledWith("season:1");
    expect(row.open).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
