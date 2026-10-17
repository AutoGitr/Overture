import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listItemsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToItemArt, goToItemThemes, goToSeason, route } from "../../../lib/router/routes";
import { selectedState } from "../../../lib/stores/selectedState.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import {
  advanceToNextItem,
  beginAutoAdvance,
  cancelPendingAutoAdvance,
  computeNextArtworkTarget,
  computeNextThemeTarget,
  handleArtworkSelectionAdvance,
  handleThemeSelectionAdvance,
  preloadNextItem,
  scheduleAutoAdvance,
  type AutoAdvanceSettings,
} from "../../../lib/utils/autoAdvance";
import { mediaItem, season } from "../../helpers/fixtures";

const { preloadImages } = vi.hoisted(() => ({ preloadImages: vi.fn() }));
vi.mock("../../../lib/utils/imagePreload", () => ({ preloadImages }));

vi.mock("../../../lib/router/routes", () => ({
  goToItemArt: vi.fn(),
  goToItemThemes: vi.fn(),
  goToSeason: vi.fn(),
  route: { pathname: "/movies/100-current/art/poster" },
}));

const baseSettings: AutoAdvanceSettings = {
  workflow: "art_and_themes",
  auto_advance: true,
  auto_advance_skip_completed: false,
};
const current = mediaItem({ id: 100 });
// Completeness is reported by the backend, which owns the rules.
const complete = mediaItem({
  id: 200,
  art_status: "complete",
  poster_status: "complete",
  background_status: "complete",
  theme_status: "complete",
});
const s1 = season({ id: 10, season_num: 1 });
const s2 = season({ id: 20, season_num: 2 });
const completedSeason = season({ ...s2, poster_status: "complete" });

function setLibrary(items: ReturnType<typeof mediaItem>[]) {
  queryClient.setQueryData(listItemsOptions().queryKey, { items, total: items.length });
  sidebarState.current = { type: "movie", itemIds: [current.id, ...items.map((item) => item.id)] };
}

beforeEach(() => {
  queryClient.clear();
  sidebarState.current = null;
  settingsState.load(baseSettings);
  selectedState.selectItem(current);
  route.pathname = "/movies/100-current/art/poster";
});

afterEach(() => {
  cancelPendingAutoAdvance();
  settingsState.load({});
  selectedState.selectItem(null);
});

describe("artwork workflow", () => {
  const options = {
    item: current,
    artType: "poster" as const,
    seasonId: null,
    seasons: [],
    settings: baseSettings,
  };

  it("advances poster to background", () => {
    expect(computeNextArtworkTarget(options)).toEqual({ type: "art", subtab: "background" });
  });

  it("does not advance between slots when that option is disabled", () => {
    expect(
      computeNextArtworkTarget({
        ...options,
        settings: { ...baseSettings, auto_advance: false },
      }),
    ).toBeNull();
  });

  it.each([
    ["art", { type: "next_item" }],
    ["art_and_themes", { type: "theme" }],
    ["themes", null],
  ] as const)("finishes artwork according to the %s workflow", (workflow, target) => {
    expect(
      computeNextArtworkTarget({
        ...options,
        artType: "background",
        settings: { ...baseSettings, workflow },
      }),
    ).toEqual(target);
  });

  it("skips a complete background and theme", () => {
    expect(
      computeNextArtworkTarget({
        ...options,
        item: complete,
        settings: { ...baseSettings, auto_advance_skip_completed: true },
      }),
    ).toEqual({ type: "next_item" });
  });

  it("visits seasons in season order", () => {
    const specials = season({ id: 5, season_num: 0 });
    expect(
      computeNextArtworkTarget({
        ...options,
        item: mediaItem({ media_type: "show" }),
        artType: "background",
        seasons: [s2, specials, s1],
      }),
    ).toEqual({ type: "season", season: specials });
  });

  it("advances through seasons and then to Themes", () => {
    const showOptions = {
      ...options,
      item: mediaItem({ media_type: "show" }),
      artType: "season_poster" as const,
      seasons: [s1, s2],
    };
    expect(computeNextArtworkTarget({ ...showOptions, seasonId: s1.id })).toEqual({
      type: "season",
      season: s2,
    });
    expect(computeNextArtworkTarget({ ...showOptions, seasonId: s2.id })).toEqual({
      type: "theme",
    });
    expect(
      computeNextArtworkTarget({
        ...showOptions,
        seasonId: s2.id,
        settings: { ...baseSettings, auto_advance: false },
      }),
    ).toBeNull();
  });

  it("skips completed remaining seasons", () => {
    expect(
      computeNextArtworkTarget({
        ...options,
        item: mediaItem({ media_type: "show" }),
        artType: "season_poster",
        seasonId: s1.id,
        seasons: [s1, completedSeason],
        settings: { ...baseSettings, auto_advance_skip_completed: true },
      }),
    ).toEqual({ type: "theme" });
  });

  it("advances from Themes only when enabled", () => {
    expect(computeNextThemeTarget(baseSettings)).toEqual({ type: "next_item" });
    expect(computeNextThemeTarget({ ...baseSettings, auto_advance: false })).toBeNull();
  });
});

describe("next item navigation", () => {
  it.each(["art", "art_and_themes", "themes"] as const)(
    "uses the %s workflow regardless of the current tab",
    (workflow) => {
      selectedState.mode = workflow === "themes" ? "art" : "themes";
      const next = mediaItem({ id: 200 });
      setLibrary([next]);
      advanceToNextItem(current, { ...baseSettings, workflow });
      if (workflow === "themes") {
        expect(goToItemThemes).toHaveBeenCalledExactlyOnceWith(next);
      } else {
        expect(goToItemArt).toHaveBeenCalledExactlyOnceWith(next, "poster");
      }
    },
  );

  it("skips complete art without requiring a theme in the art workflow", () => {
    const next = mediaItem({ id: 300 });
    setLibrary([mediaItem({ ...complete, theme_status: "partial" }), next]);
    advanceToNextItem(current, {
      ...baseSettings,
      workflow: "art",
      auto_advance_skip_completed: true,
    });
    expect(goToItemArt).toHaveBeenCalledExactlyOnceWith(next, "poster");
    expect(goToItemThemes).not.toHaveBeenCalled();
  });

  it("stops at the end without wrapping", () => {
    sidebarState.current = { type: "movie", itemIds: [current.id] };
    expect(advanceToNextItem(current, baseSettings)).toBe(false);
    expect(goToItemArt).not.toHaveBeenCalled();
  });

  it("skips complete cached items and lands on the first incomplete slot", () => {
    const next = mediaItem({
      ...complete,
      id: 300,
      art_status: "partial",
      background_status: "missing",
    });
    setLibrary([complete, next]);
    expect(advanceToNextItem(current, { ...baseSettings, auto_advance_skip_completed: true })).toBe(
      true,
    );
    expect(goToItemArt).toHaveBeenCalledExactlyOnceWith(next, "background");
  });

  it("opens Themes for an item whose art is complete", () => {
    const next = mediaItem({ ...complete, theme_status: "missing" });
    setLibrary([next]);
    advanceToNextItem(current, { ...baseSettings, auto_advance_skip_completed: true });
    expect(goToItemThemes).toHaveBeenCalledExactlyOnceWith(next);
  });

  it("skips complete themes even if their artwork is missing", () => {
    selectedState.mode = "themes";
    const next = mediaItem({ id: 300 });
    setLibrary([mediaItem({ id: 200, theme_status: "complete" }), next]);
    advanceToNextItem(current, {
      ...baseSettings,
      workflow: "themes",
      auto_advance_skip_completed: true,
    });
    expect(goToItemThemes).toHaveBeenCalledExactlyOnceWith(next);
  });

  it.each(["cached", "uncached"])("preserves the themes workflow for %s items", (cache) => {
    selectedState.mode = "themes";
    const next = mediaItem({ id: 200 });
    if (cache === "cached") setLibrary([next]);
    else sidebarState.current = { type: "movie", itemIds: [100, 200] };
    advanceToNextItem(current, { ...baseSettings, workflow: "themes" });
    expect(goToItemThemes).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ id: 200, media_type: "movie" }),
    );
  });

  it("uses the list captured before a save changes its filter/order", () => {
    vi.useFakeTimers();
    selectedState.mode = "themes";
    setLibrary([mediaItem({ id: 200 })]);
    const context = beginAutoAdvance();
    sidebarState.current = { type: "movie", itemIds: [200] };
    settingsState.load({
      ...baseSettings,
      workflow: "themes",
    });
    handleThemeSelectionAdvance(current, context);
    vi.advanceTimersByTime(300);
    expect(goToItemThemes).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: 200 }));
  });
});

describe("asynchronous navigation safety", () => {
  it("waits for the configured delay", () => {
    vi.useFakeTimers();
    const action = vi.fn();
    scheduleAutoAdvance(action, beginAutoAdvance(), 300);
    vi.advanceTimersByTime(299);
    expect(action).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(action).toHaveBeenCalledOnce();
  });

  it.each([0, 300])("ignores late responses after leaving the item (delay %s)", (delay) => {
    vi.useFakeTimers();
    const context = beginAutoAdvance();
    selectedState.selectItem(mediaItem({ id: 200 }));
    const action = vi.fn();
    scheduleAutoAdvance(action, context, delay);
    vi.runAllTimers();
    expect(action).not.toHaveBeenCalled();
  });

  it("does not override a manual tab change on the same item", () => {
    vi.useFakeTimers();
    const action = vi.fn();
    scheduleAutoAdvance(action, beginAutoAdvance(), 300);
    route.pathname = "/movies/100-current/themes";
    vi.runAllTimers();
    expect(action).not.toHaveBeenCalled();
  });

  it("invalidates in-flight work even when the user returns to the original route", () => {
    const context = beginAutoAdvance();
    cancelPendingAutoAdvance();
    const action = vi.fn();
    scheduleAutoAdvance(action, context, 0);
    expect(action).not.toHaveBeenCalled();
  });

  it("keeps a newer timer when an older response arrives", () => {
    vi.useFakeTimers();
    const oldContext = beginAutoAdvance();
    const currentAction = vi.fn();
    scheduleAutoAdvance(currentAction, beginAutoAdvance(), 300);
    const oldAction = vi.fn();
    scheduleAutoAdvance(oldAction, oldContext, 0);
    vi.advanceTimersByTime(300);
    expect(currentAction).toHaveBeenCalledOnce();
    expect(oldAction).not.toHaveBeenCalled();
  });

  it("waits for seasons instead of mistaking a pending query for no seasons", async () => {
    const show = mediaItem({ id: 100, media_type: "show" });
    selectedState.selectItem(show);
    vi.useFakeTimers();
    settingsState.load(baseSettings);
    let resolveSeasons!: (seasons: ReturnType<typeof season>[]) => void;
    vi.spyOn(queryClient, "fetchQuery").mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSeasons = resolve;
        }),
    );
    const pending = handleArtworkSelectionAdvance({
      item: show,
      artType: "background",
      seasonId: null,
      context: beginAutoAdvance(),
    });
    expect(goToItemThemes).not.toHaveBeenCalled();
    resolveSeasons([s1]);
    await pending;
    vi.advanceTimersByTime(300);
    expect(goToSeason).toHaveBeenCalledExactlyOnceWith(show, s1);
  });

  it("rechecks cancellation after the seasons request finishes", async () => {
    const show = mediaItem({ id: 100, media_type: "show" });
    selectedState.selectItem(show);
    vi.useFakeTimers();
    settingsState.load(baseSettings);
    let resolveSeasons!: (seasons: ReturnType<typeof season>[]) => void;
    vi.spyOn(queryClient, "fetchQuery").mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSeasons = resolve;
        }),
    );
    const pending = handleArtworkSelectionAdvance({
      item: show,
      artType: "background",
      seasonId: null,
      context: beginAutoAdvance(),
    });
    cancelPendingAutoAdvance();
    resolveSeasons([s1]);
    await pending;
    vi.advanceTimersByTime(300);
    expect(goToSeason).not.toHaveBeenCalled();
  });
});

describe("next item preloading", () => {
  it("fetches the detail images of the item auto-advance would open", () => {
    const next = mediaItem({
      id: 300,
      folder_path: "/movies/Next",
      poster_hash: "p3",
      background_hash: "b3",
    });
    setLibrary([complete, next]);
    settingsState.show_background_image = true;

    preloadNextItem(current, { ...baseSettings, auto_advance_skip_completed: true });

    expect(preloadImages).toHaveBeenCalledExactlyOnceWith(
      [
        "/api/library/items/300/local-image/poster?t=p3",
        "/api/library/items/300/local-image/background?t=b3&size=display",
      ],
      "next",
    );
  });

  it("fetches nothing when auto-advance is off or there is no next item", () => {
    setLibrary([mediaItem({ id: 300 })]);
    preloadNextItem(current, { ...baseSettings, auto_advance: false });
    sidebarState.current = { type: "movie", itemIds: [current.id] };
    preloadNextItem(current, baseSettings);

    expect(preloadImages).not.toHaveBeenCalled();
  });
});
