import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { listCollectionsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { queryClient } from "../../../lib/rest/queryClient";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import {
  beginAutoAdvance,
  cancelPendingAutoAdvance,
  type AutoAdvanceSettings,
} from "../../../lib/utils/autoAdvance";
import type { CatalogContext } from "../../../lib/utils/catalogDraft";
import * as imagePreload from "../../../lib/utils/imagePreload";
import {
  catalogPageRecord,
  collectionRecord,
  handleRecordSelectionAdvance,
  nextRecordTarget,
  openNextRecord,
  preloadNextCollection,
  type AdvanceRecord,
  type RecordSlot,
} from "../../../lib/utils/recordAdvance";
import { appSettings, catalogDetail, catalogEntry, collection } from "../../helpers/fixtures";
import { searchInSidebar, showInSidebar } from "../../helpers/sidebar";

vi.mock("../../../lib/router/routes", () => ({
  route: { pathname: "/overturedb/collections/tmdb-1/art/poster" },
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
  showInSidebar({ records: null });
  sidebarState.searched = null;
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
    showInSidebar({ records: rows });
    const context = beginAutoAdvance();
    showInSidebar({ records: [] });

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
    showInSidebar({ records: [row] });

    handleRecordSelectionAdvance("a", "background", beginAutoAdvance(), page);
    vi.runAllTimers();
    expect(page.open).toHaveBeenCalledWith("season:1");
    expect(row.open).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("goes through the TMDB results shown while the sidebar searches TMDB", () => {
    vi.useFakeTimers();
    const listed = record("b");
    const found = record("c");
    showInSidebar({ records: [record("a", {}, ["theme"]), listed] });
    searchInSidebar({ records: [record("a", {}, ["theme"]), found] });

    handleRecordSelectionAdvance("a", "theme", beginAutoAdvance());
    vi.runAllTimers();
    expect(found.open).toHaveBeenCalledWith("poster");
    expect(listed.open).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});

describe("a catalog page", () => {
  it("counts a collection's poster of the style shown", () => {
    const entry = catalogEntry({
      media_type: "collection",
      poster_url_matte: "https://image.tmdb.org/t/p/original/matte.jpg",
    });
    const page = catalogPageRecord({
      detail: catalogDetail({ entry }),
      entry,
      posterField: "poster_url_matte",
      target: { media_type: "collection", entry_key: "tmdb-1" },
      draft: {} as CatalogContext["draft"],
      seasons: [],
    });
    expect(page.slots.find(({ slot }) => slot === "poster")?.complete).toBe(true);
  });
});

describe("next collection preloading", () => {
  it("fetches the detail images of the collection auto-advance would open next", () => {
    const spy = vi.spyOn(imagePreload, "preloadImages").mockImplementation(() => {});
    const first = collection({ id: 1, title: "First" });
    const done = collection({
      id: 2,
      title: "Done",
      assets: {
        poster: { status: "complete" },
        background: { status: "complete" },
        theme: { status: "complete" },
      },
    });
    const next = collection({
      id: 3,
      title: "Next",
      server_poster_version: "p3",
      server_background_version: "b3",
    });
    queryClient.setQueryData(listCollectionsOptions().queryKey, [first, done, next]);
    showInSidebar({
      records: [collectionRecord(first), collectionRecord(done), collectionRecord(next)],
    });
    settingsState.show_background_image = true;

    preloadNextCollection(1, { ...settings, auto_advance: "off" });
    preloadNextCollection(99, settings);
    expect(spy).not.toHaveBeenCalled();

    preloadNextCollection(1, { ...settings, auto_advance_skip_completed: true });
    expect(spy).toHaveBeenCalledExactlyOnceWith(
      [
        "/api/collections/3/image/poster?t=p3&size=display",
        "/api/collections/3/image/background?t=b3&size=display",
      ],
      "next",
    );
    queryClient.clear();
    spy.mockRestore();
  });
});
