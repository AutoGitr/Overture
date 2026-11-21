import { describe, expect, it } from "vitest";
import { catalogFilterCount, defaultCatalogFilters } from "../../../lib/utils/sidebarFilters";

describe("catalog filter count", () => {
  it("counts the filters that narrow the list, season posters only for shows", () => {
    const filters = {
      ...defaultCatalogFilters(),
      poster: "present",
      seasonPosters: "missing",
    } as const;
    expect(catalogFilterCount(defaultCatalogFilters(), "show")).toBe(0);
    expect(catalogFilterCount(filters, "show")).toBe(2);
    expect(catalogFilterCount(filters, "movie")).toBe(1);
  });
});
