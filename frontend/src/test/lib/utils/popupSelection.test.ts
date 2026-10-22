import { describe, expect, it } from "vitest";
import {
  allValuesSelected,
  filterAvailableValues,
  selectedValuesForAll,
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
});
