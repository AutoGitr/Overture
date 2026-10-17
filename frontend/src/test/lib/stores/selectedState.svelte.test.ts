import { beforeEach, describe, expect, it } from "vitest";

import { selectedState } from "../../../lib/stores/selectedState.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { mediaItem } from "../../helpers/fixtures";

const show = mediaItem({
  id: 7,
  title: "Twin Peaks",
  media_type: "show",
});

describe("selectedState", () => {
  beforeEach(() => {
    settingsState.load({ workflow: "themes" });
    selectedState.selectItem(null);
    selectedState.mode = "art";
    selectedState.artSubTab = "poster";
  });

  it("selects an item, persists its id, and applies the configured default tab", () => {
    selectedState.selectItem(show);

    expect(selectedState.item).toEqual(show);
    expect(selectedState.mode).toBe("themes");
  });

  it("clears drill state when changing item", () => {
    selectedState.selectItem(show);
    selectedState.drillSeasonNum = 1;

    selectedState.selectItem(null);

    expect(selectedState.item).toBeNull();
    expect(selectedState.drillSeasonNum).toBeNull();
  });

  it("names a real art slot on the seasons tab, drilled or not", () => {
    selectedState.selectItem(show);
    selectedState.artSubTab = "seasons";
    selectedState.drillSeasonNum = 1;

    expect(selectedState.currentArtType).toBe("season_poster");

    selectedState.drillSeasonNum = null;

    expect(selectedState.currentArtType).toBe("season_poster");
  });
});
