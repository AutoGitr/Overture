import { describe, expect, it } from "vitest";
import {
  allValuesSelected,
  filterAvailableValues,
  selectedValuesForAll,
  toggleCollectionChoice,
  toggleSelectedValue,
} from "../../../lib/utils/popupSelection";

describe("popup selection helpers", () => {
  it("restores only available values and toggles without mutation", () => {
    const selected = ["movie", "removed"];

    expect(filterAvailableValues(selected, ["movie", "show"])).toEqual(["movie"]);
    expect(toggleSelectedValue(selected, "show")).toEqual(["movie", "removed", "show"]);
    expect(toggleSelectedValue(selected, "movie")).toEqual(["removed"]);
    expect(selected).toEqual(["movie", "removed"]);
  });

  it("selects and clears all values while treating an empty list as unselected", () => {
    expect(selectedValuesForAll(true, ["movie", "show"])).toEqual(["movie", "show"]);
    expect(selectedValuesForAll(false, ["movie", "show"])).toEqual([]);
    expect(allValuesSelected(["movie", "show"], ["movie", "show"])).toBe(true);
    expect(allValuesSelected([], [])).toBe(false);
  });

  it("chooses every collection or groups, never both", () => {
    const groups = { all: false, groups: ["Sagas"] };

    expect(toggleCollectionChoice(groups, null)).toEqual({ all: true, groups: [] });
    expect(toggleCollectionChoice({ all: true, groups: [] }, "Decades")).toEqual({
      all: false,
      groups: ["Decades"],
    });
    expect(toggleCollectionChoice(groups, "Sagas")).toEqual({ all: false, groups: [] });
    expect(groups).toEqual({ all: false, groups: ["Sagas"] });
  });
});
