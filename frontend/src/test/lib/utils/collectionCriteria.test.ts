import { describe, expect, it } from "vitest";
import {
  conditionFits,
  groupFits,
  availableFields,
  availableOrders,
  defaultValue,
  emptyGroup,
  fieldCondition,
  franchiseCriteria,
  groupIsEmpty,
  newSource,
  parseIds,
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

  it("offers only the operators the chosen evaluation tests", () => {
    const resolution = {
      ...field("genre"),
      field: "resolution" as const,
      operators: ["is" as const, "is_not" as const],
      smart_operators: ["is" as const],
    };
    const fields = { ...capabilities, fields: [resolution] };
    expect(availableFields(fields, false)[0]?.operators).toEqual(["is", "is_not"]);
    expect(availableFields(fields, true)[0]?.operators).toEqual(["is"]);
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
    expect(parseIds("abc, -1, 0, 10, 20\n30, 0.5")).toEqual({
      ids: [10, 20, 30],
      invalid: ["abc", "-1", "0", "0.5"],
    });
    expect(
      parseIds("https://www.themoviedb.org/list/8136-best, https://www.themoviedb.org/movie/550/")
        .ids,
    ).toEqual([8136, 550]);
  });

  it("pastes what the target criteria can test, wherever they belong", () => {
    const fields = [{ ...field("genre"), operators: ["is" as const, "is_not" as const] }];
    const sources = capabilities.sources;
    const movies = { fields, sources, mediaType: "movie" as const };
    const shows = { fields, sources, mediaType: "show" as const };
    const genre = {
      kind: "field" as const,
      field: "genre" as const,
      operator: "is" as const,
      value: "Drama",
    };

    // Another library of either media type takes a field both offer.
    expect(conditionFits(genre, shows, "movie")).toBe(true);
    expect(conditionFits({ ...genre, operator: "contains" }, shows, "movie")).toBe(false);
    expect(conditionFits({ ...genre, field: "studio" }, shows, "movie")).toBe(false);

    // A TMDB title ID names another title in the other media type.
    const titles = {
      kind: "source" as const,
      operator: "is" as const,
      source: { type: "tmdb_item" as const, tmdb_ids: [550] },
    };
    expect(conditionFits(titles, movies, "movie")).toBe(true);
    expect(conditionFits(titles, shows, "movie")).toBe(false);
    expect(
      conditionFits(
        titles,
        { ...movies, sources: sources.filter((s) => s.type !== "tmdb_item") },
        "movie",
      ),
    ).toBe(false);

    expect(
      groupFits(
        {
          mode: "any",
          conditions: [genre],
          groups: [{ mode: "all", conditions: [titles], groups: [] }],
        },
        shows,
        "movie",
      ),
    ).toBe(false);
    expect(groupFits({ mode: "any", conditions: [genre], groups: [] }, shows, "movie")).toBe(true);
  });
});
