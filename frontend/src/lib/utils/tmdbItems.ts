import type { CatalogMediaType, MediaItemRead } from "../../generated/rest/types.gen";
import type { CatalogDraft } from "./catalogDraft";
import { upsertLibraryItem } from "../rest/cache";
import { beginAutoAdvance, handleFirstSelectionAdvance, type FirstSelection } from "./autoAdvance";

/** The artwork slot a panel saves into: of a stored item, or of a TMDB title. */
export type ArtSlotTarget =
  | {
      kind: "catalog";
      draft: CatalogDraft;
      mediaType: CatalogMediaType;
      entryKey: string;
      tmdbId: number | null;
      seasonNum: number | null;
    }
  | { kind: "item"; itemId: number; seasonId: number | null }
  | {
      kind: "tmdb";
      mediaType: MediaItemRead["media_type"];
      tmdbId: number;
      seasonNum: number | null;
    };

/**
 * Show the item a TMDB title's first selection stored: in the library at
 * once, and in the detail view as auto-advance decides. Nothing moves if the
 * user has navigated away meanwhile.
 */
export async function openPersistedItem(
  item: MediaItemRead,
  selection: FirstSelection,
  context: ReturnType<typeof beginAutoAdvance>,
): Promise<void> {
  upsertLibraryItem(item);
  await handleFirstSelectionAdvance(item, selection, context);
}
