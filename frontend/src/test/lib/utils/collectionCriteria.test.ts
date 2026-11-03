import { describe, expect, it } from "vitest";
import {
  availableFields,
  availableOrders,
  defaultValue,
  emptyGroup,
  fieldCondition,
  franchiseCriteria,
  groupIsEmpty,
  newSource,
  splitIds,
  splitList,
} from "../../../lib/utils/collectionCriteria";
import { collectionCapabilities } from "../../helpers/fixtures";

describe("collection criteria helpers", () => {
  const capabilities = collectionCapabilities();
  const field = (name: string) => {
    const found = capabilities.fields.find((entry) => entry.field === name);
    if (!found) throw new Error(`No ${name} field`);
    return found;
  };

  it("offers the fields and orders of the chosen evaluation", () => {
    expect(availableFields(capabilities, false).map((entry) => entry.field)).not.toContain("hdr");
    expect(availableFields(capabilities, true).map((entry) => entry.field)).toContain("hdr");
    expect(availableOrders(capabilities, false)).toContain("custom");
    expect(availableOrders(capabilities, true)).not.toContain("custom");
    expect(availableFields(undefined, true)).toEqual([]);
  });

  it("starts each condition with a value of its kind", () => {
    expect(fieldCondition(field("genre"))).toEqual({
      kind: "field",
      field: "genre",
      operator: "is",
      value: "",
    });
    expect(fieldCondition(field("unplayed"))).toMatchObject({ value: true });
    expect(fieldCondition(field("year"))).toMatchObject({ value: 30 });
    expect(fieldCondition(field("added"))).toMatchObject({ operator: "in_last", value: 30 });
    expect(defaultValue(field("added"), "before")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("creates every source and recognises empty groups", () => {
    expect(newSource("tmdb_person")).toEqual({
      type: "tmdb_person",
      person_id: 0,
      roles: ["actor"],
    });
    expect(newSource("tmdb_chart")).toEqual({ type: "tmdb_chart", chart: "popular", limit: 100 });
    expect(newSource("mdblist")).toEqual({ type: "mdblist", identifiers: [] });
    expect(groupIsEmpty({ ...emptyGroup(), groups: [emptyGroup("any")] })).toBe(true);
    expect(groupIsEmpty(franchiseCriteria(10))).toBe(false);
  });

  it("splits text into trimmed lists and positive IDs", () => {
    expect(splitList("  \n  ,  \n")).toEqual([]);
    expect(splitList("first\nsecond, third")).toEqual(["first", "second", "third"]);
    expect(splitIds("abc, -1, 0, 10, 20\n30, 0.5")).toEqual([10, 20, 30]);
  });
});
