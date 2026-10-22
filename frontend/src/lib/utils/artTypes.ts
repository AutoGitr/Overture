/** The artwork slots and the theme, as the UI names and colours them. */
import type { ServerAsset } from "../../generated/rest/types.gen";
import { SEASON_ART_TYPES } from "../../generated/settings";

export const ASSET_LABELS: Record<ServerAsset, string> = {
  poster: "Poster",
  background: "Background",
  season_poster: "Season Poster",
  theme: "Theme",
};

export const ASSET_BADGES: Record<ServerAsset, string> = {
  poster: "badge-art",
  background: "badge-art",
  season_poster: "badge-art",
  theme: "badge-theme",
};

/** Whether an artwork slot exists only on shows, whose seasons hold it. */
export function isSeasonArtType(asset: ServerAsset): boolean {
  return (SEASON_ART_TYPES as readonly ServerAsset[]).includes(asset);
}

/**
 * The chosen assets a job's scope has targets for: none without a selection,
 * and season artwork only when the scope reaches shows.
 */
export function assetsInScope<T extends ServerAsset>(
  assets: readonly T[],
  scope: { hasSelection: boolean; hasShows: boolean },
): T[] {
  if (!scope.hasSelection) return [];
  return assets.filter((asset) => scope.hasShows || !isSeasonArtType(asset));
}
