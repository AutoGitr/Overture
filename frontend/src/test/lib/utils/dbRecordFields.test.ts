import { describe, expect, it } from "vitest";
import { dbRecordFields } from "../../../lib/utils/dbRecordFields";
import { season as fixtureSeason } from "../../helpers/fixtures";

describe("database record field formatting", () => {
  it("lists every field in the record's own order", () => {
    expect(dbRecordFields({ title: "Alien", art_status: "partial", id: 1 })).toEqual([
      { key: "title", value: "Alien" },
      { key: "art_status", value: "partial" },
      { key: "id", value: "1" },
    ]);
  });

  it("flattens nested objects on records that still contain them", () => {
    const fields = dbRecordFields(
      fixtureSeason({
        poster_height: 1500,
        poster_width: 1000,
      }),
    );

    expect(fields).toEqual(
      expect.arrayContaining([
        { key: "poster_height", value: "1500" },
        { key: "poster_width", value: "1000" },
      ]),
    );
    expect(fields.some((field) => field.value === "[object Object]")).toBe(false);
  });

  it("flattens nested values in insertion order", () => {
    const fields = dbRecordFields({ nested: { a: 1, b: 2 }, top: 1 });

    expect(fields).toEqual([
      { key: "nested.a", value: "1" },
      { key: "nested.b", value: "2" },
      { key: "top", value: "1" },
    ]);
  });

  it.each([
    ["null", null, "null"],
    ["undefined", undefined, "undefined"],
    ["a boolean", false, "false"],
    ["a bigint", 12n, "12"],
    ["an empty list", [], "[]"],
    ["a list", [1, "a"], '[1,"a"]'],
    ["an empty object", {}, "{}"],
    ["a class instance", new Date("2026-01-02T03:04:05Z"), '"2026-01-02T03:04:05.000Z"'],
  ])("shows %s as text", (_label, value, expected) => {
    expect(dbRecordFields({ value })).toEqual([{ key: "value", value: expected }]);
  });

  it("marks a value that cannot be serialised instead of failing", () => {
    const cyclic: unknown[] = [];
    cyclic.push(cyclic);

    expect(dbRecordFields({ cyclic })).toEqual([{ key: "cyclic", value: "unserializable" }]);
  });

  it("has no fields for a missing record", () => {
    expect(dbRecordFields(null)).toEqual([]);
    expect(dbRecordFields(undefined)).toEqual([]);
  });
});
