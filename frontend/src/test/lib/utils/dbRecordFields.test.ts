import { describe, expect, it } from "vitest";
import { dbRecordFields } from "../../../lib/utils/dbRecordFields";
import { season as fixtureSeason, mediaItem } from "../../helpers/fixtures";

describe("database record field formatting", () => {
  it("orders flat art and theme fields predictably", () => {
    const fields = dbRecordFields(
      mediaItem({
        art_status: "partial",
        poster_url: "https://image.test/poster.jpg",
        poster_preview_url: "https://image.test/poster-small.jpg",
        youtube_id: "abc123_DEF0",
      }),
    );

    expect(fields).toEqual(
      expect.arrayContaining([
        { key: "poster_url", value: "https://image.test/poster.jpg" },
        { key: "youtube_id", value: "abc123_DEF0" },
      ]),
    );
    expect(
      fields.filter((field) => field.key.startsWith("poster")).map((field) => field.key),
    ).toEqual([
      "poster_url",
      "poster_source",
      "poster_hash",
      "poster_phash",
      "poster_width",
      "poster_height",
    ]);
    // The tabs show completeness by colour; the record lists only what is stored.
    expect(fields.some((field) => field.key.endsWith("_status"))).toBe(false);
    expect(fields.some((field) => field.value === "[object Object]")).toBe(false);
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

  it("falls back to insertion order plus recursive flattening for unranked nested values", () => {
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

  it("leaves out display renditions and empty records", () => {
    expect(dbRecordFields({ poster_preview_url: "https://image.test/small.jpg" })).toEqual([]);
    expect(dbRecordFields(null)).toEqual([]);
    expect(dbRecordFields(undefined)).toEqual([]);
  });
});
