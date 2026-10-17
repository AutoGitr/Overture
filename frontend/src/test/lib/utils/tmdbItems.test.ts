import { beforeEach, describe, expect, it, vi } from "vitest";
import { queryClient } from "../../../lib/rest/queryClient";
import { findCachedLibraryItem, upsertLibraryItem } from "../../../lib/rest/cache";
import {
  goToItemArt,
  goToItemThemes,
  goToItemView,
  goToSeason,
  route,
} from "../../../lib/router/routes";
import { selectedState } from "../../../lib/stores/selectedState.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import {
  AUTO_ADVANCE_DELAY_MS,
  beginAutoAdvance,
  cancelPendingAutoAdvance,
} from "../../../lib/utils/autoAdvance";
import { openPersistedItem } from "../../../lib/utils/tmdbItems";
import { mediaItem, season } from "../../helpers/fixtures";

vi.mock("../../../lib/rest/cache", () => ({
  upsertLibraryItem: vi.fn(),
  findCachedLibraryItem: vi.fn(),
}));
vi.mock("../../../lib/router/routes", () => ({
  goToItemArt: vi.fn(),
  goToItemThemes: vi.fn(),
  goToItemView: vi.fn(),
  goToSeason: vi.fn(),
  route: { pathname: "/movies/tmdb-603-matrix/art/poster" },
}));

const stored = mediaItem({ id: 7, tmdb_id: 603, title: "The Matrix" });
const poster = { artType: "poster" as const, seasonNum: null };
const sameView = { mode: "art", artSubTab: "poster", drillSeasonNum: null };

describe("persisting a TMDB preview", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    settingsState.load({ auto_advance: false, workflow: "art_and_themes" });
    selectedState.selectItem(null);
    selectedState.mode = "art";
    route.pathname = "/movies/tmdb-603-matrix/art/poster";
    sidebarState.current = null;
    sidebarState.tmdbResults = [
      { kind: "tmdb", tmdb_id: 603, title: "The Matrix", media_type: "movie" },
      { kind: "item", id: 9 },
      { kind: "tmdb", tmdb_id: 605, title: "The Matrix Revolutions", media_type: "movie" },
    ];
  });

  it("opens the stored item in the same view at once without auto-advance", async () => {
    await openPersistedItem(stored, poster, beginAutoAdvance());

    expect(upsertLibraryItem).toHaveBeenCalledWith(stored);
    expect(goToItemView).toHaveBeenCalledExactlyOnceWith(stored, sameView, { replace: true });
    expect(goToItemArt).not.toHaveBeenCalled();
  });

  it("replaces the title with the item, then advances to the next slot", async () => {
    settingsState.load({ auto_advance: true, workflow: "art_and_themes" });

    await openPersistedItem(stored, poster, beginAutoAdvance());
    expect(goToItemView).not.toHaveBeenCalled();
    vi.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS);

    expect(goToItemView).toHaveBeenCalledWith(stored, sameView, { replace: true });
    expect(goToItemArt).toHaveBeenCalledExactlyOnceWith(stored, "background");
  });

  it("moves from a show's season poster to its next season", async () => {
    settingsState.load({ auto_advance: true, workflow: "art" });
    const show = mediaItem({ id: 8, media_type: "show" });
    const next = season({ id: 82, media_item_id: 8, season_num: 1 });
    vi.spyOn(queryClient, "fetchQuery").mockResolvedValue([
      season({ id: 81, media_item_id: 8, season_num: 0 }),
      next,
    ]);

    await openPersistedItem(show, { artType: "season_poster", seasonNum: 0 }, beginAutoAdvance());
    vi.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS);

    expect(goToSeason).toHaveBeenCalledExactlyOnceWith(show, next);
  });

  it("moves on to the next TMDB result once the item is done", async () => {
    settingsState.load({ auto_advance: true, workflow: "themes" });
    selectedState.mode = "themes";
    vi.mocked(findCachedLibraryItem).mockReturnValue(
      mediaItem({ id: 9, theme_status: "complete" }),
    );
    settingsState.current.auto_advance_skip_completed = true;

    await openPersistedItem(stored, { theme: true }, beginAutoAdvance());
    vi.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS);

    // The stored result 9 is complete, so the new title after it is next.
    expect(goToItemThemes).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ tmdb_id: 605, title: "The Matrix Revolutions" }),
    );
  });

  it("updates the library without navigating when the user has moved away", async () => {
    const context = beginAutoAdvance();
    route.pathname = "/movies";
    await openPersistedItem(stored, poster, context);

    expect(upsertLibraryItem).toHaveBeenCalledWith(stored);
    expect(goToItemView).not.toHaveBeenCalled();
  });

  it("does not take over a later visit to the same route", async () => {
    const context = beginAutoAdvance();
    cancelPendingAutoAdvance();
    await openPersistedItem(stored, poster, context);

    expect(goToItemView).not.toHaveBeenCalled();
  });
});
