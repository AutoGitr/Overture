import { describe, expect, it } from "vitest";
import type { FilterGroupInput } from "../../../generated/rest/types.gen";
import {
  criteriaPredicate,
  isEmptyCriteria,
  serverConditions,
} from "../../../lib/utils/libraryCriteria";
import { mediaItem } from "../../helpers/fixtures";

const horror = { kind: "field", field: "genre", operator: "is", value: "Horror" } as const;
const unarted = { kind: "field", field: "art_status", operator: "is", value: "MISSING" } as const;
const narrow = { kind: "field", field: "poster_width", operator: "lt", value: 1000 } as const;
const unmonitored = { kind: "field", field: "monitored", operator: "is", value: false } as const;

describe("library criteria", () => {
  it("asks the server only about metadata and sources, in evaluation order", () => {
    const actor = { kind: "field", field: "actor", operator: "is", value: "Lead" } as const;
    const group: FilterGroupInput = {
      mode: "all",
      conditions: [horror, unarted],
      groups: [{ mode: "any", conditions: [narrow, actor] }],
    };

    expect(serverConditions(group)).toEqual([horror, actor]);
  });

  it("combines live status with what the server matched", () => {
    const items = [
      mediaItem({
        id: 1,
        title: "Unarted horror",
        art_status: "missing",
        assets: { poster: { width: null } },
      }),
      mediaItem({
        id: 2,
        title: "Narrow horror",
        art_status: "complete",
        assets: { poster: { width: 500 } },
      }),
      mediaItem({ id: 3, title: "Unarted drama", art_status: "missing" }),
      mediaItem({ id: 4, title: "Unmonitored horror", art_status: "complete", monitored: false }),
    ];
    const group: FilterGroupInput = {
      mode: "all",
      conditions: [horror],
      groups: [{ mode: "any", conditions: [unarted, narrow, unmonitored] }, { mode: "all" }],
    };

    const matches = criteriaPredicate(group, [[1, 2, 4]]);

    // Tags compare without case, as the server compares them.
    expect(items.filter(matches).map((item) => item.title)).toEqual([
      "Unarted horror",
      "Narrow horror",
      "Unmonitored horror",
    ]);
    expect(isEmptyCriteria({ mode: "all", groups: [{ mode: "any" }] })).toBe(true);
    expect(isEmptyCriteria(group)).toBe(false);
  });
});
