import type { CatalogSelections } from "../../generated/rest/types.gen";

/** Each OvertureDB selections filter, by the slot of `catalog_selections` it reads. */
export const CATALOG_SELECTION_FILTERS = {
  catalogPoster: "poster",
  catalogBackground: "background",
  catalogSeasonPosters: "season_posters",
  catalogTheme: "theme",
} as const satisfies Record<string, keyof CatalogSelections>;

export type CatalogSelectionFilter = keyof typeof CATALOG_SELECTION_FILTERS;
/** What a selections filter keeps: every title, or those that match or differ. */
export type SelectionAgreement = "all" | "matching" | "different";
export const SELECTION_AGREEMENTS = ["all", "matching", "different"] as const;
