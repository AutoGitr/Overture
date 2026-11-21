import { describe, expect, it } from "vitest";
import {
  collectionGroupRows,
  normalizeSortPreference,
  sortCollectionGroups,
  sortMenu,
} from "../../../lib/utils/sidebarSorts";
import { collection } from "../../helpers/fixtures";

describe("sidebar sort preferences", () => {
  it.each(["library", "collections", "overturedb"] as const)(
    "preserves every %s sort and rejects the others",
    (scope) => {
      for (const { id } of sortMenu(scope)) {
        expect(normalizeSortPreference({ field: id, dir: "desc" }, scope)).toEqual({
          field: id,
          dir: "desc",
        });
      }
      expect(normalizeSortPreference({ field: "child_count", dir: "desc" }, "library").field).toBe(
        "title",
      );
    },
  );

  it.each([null, [], "invalid", {}, { field: 42, dir: "sideways" }])(
    "defaults malformed preferences",
    (value) => {
      expect(normalizeSortPreference(value, "library")).toEqual({ field: "title", dir: "asc" });
    },
  );

  it("offers each list its own sort fields", () => {
    expect(sortMenu("overturedb").map((entry) => entry.id)).toEqual([
      "title",
      "year",
      "completeness",
      "has_draft",
      "in_library",
    ]);
    expect(sortMenu("collections").map((entry) => entry.id)).toContain("child_count");
    expect(sortMenu("library").map((entry) => entry.id)).not.toContain("child_count");
  });
});

describe("collection and group sorts", () => {
  const ids = (scope: Parameters<typeof sortMenu>[0], context?: Parameters<typeof sortMenu>[1]) =>
    sortMenu(scope, context).map((entry) => entry.id);

  it("offers collections only what they all have a value for", () => {
    expect(ids("collections", { plex: true })).toEqual([
      "title",
      "sort_title",
      "group",
      "home_order",
      "child_count",
      "server_added_at",
      "last_synced_at",
    ]);
  });

  it("drops what says nothing about the list shown", () => {
    expect(ids("collections", { inGroup: true })).not.toContain("group");
    expect(ids("collections", { plex: false })).not.toContain("home_order");
  });

  it("sorts groups by what their collections add up to", () => {
    expect(ids("groups")).toEqual([
      "title",
      "collection_count",
      "child_count",
      "server_added_at",
      "last_synced_at",
    ]);
    const rows = collectionGroupRows(
      ["Small", "Large", "Empty"],
      [
        collection({ id: 1, managed: true, collection_group: "Small", child_count: 1 }),
        collection({ id: 2, managed: true, collection_group: "Large", child_count: 4 }),
        collection({ id: 3, managed: true, collection_group: "Large", child_count: 5 }),
      ],
    );
    expect(rows.map((row) => [row.title, row.collections, row.items])).toEqual([
      ["Small", 1, 1],
      ["Large", 2, 9],
      ["Empty", 0, 0],
    ]);
    expect(sortCollectionGroups(rows, "child_count", "desc").map((row) => row.title)).toEqual([
      "Large",
      "Small",
      "Empty",
    ]);
    expect(sortCollectionGroups(rows, "title", "desc").map((row) => row.title)).toEqual([
      "Small",
      "Large",
      "Empty",
    ]);
  });
});
